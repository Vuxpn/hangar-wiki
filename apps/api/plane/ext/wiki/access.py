# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Who may see and change wiki collections and pages.

One policy serves the web app and the API-key endpoints, so the two cannot
drift apart. Levels follow the collection member access values:

- ``NONE`` (-1): the collection or page does not exist for the caller;
- ``VIEW`` (0) / ``COMMENT`` (1): read only;
- ``EDIT`` (2): create, edit, file and archive pages.

Rules:

- A public collection gives every active workspace Admin and Member ``EDIT``.
  Guests see nothing unless they are added as collection members.
- A private collection is visible only to its owner and its members, whatever
  their workspace role: it exists for pages that a team keeps to itself.
- An explicit membership never lowers what the role already grants.
- A private page (``access=1``) is visible to its owner only, as in projects.
- A page that sits in no collection is treated as filed in a public one.
"""

# Django imports
from django.db.models import Exists, OuterRef, Q, QuerySet

# Module imports
from plane.app.permissions import ROLE
from plane.db.models import Page, WorkspaceMember
from plane.ext.models import WikiCollection, WikiCollectionMember, WikiPageCollection

NONE = -1
VIEW = WikiCollectionMember.VIEW
COMMENT = WikiCollectionMember.COMMENT
EDIT = WikiCollectionMember.EDIT


def workspace_role(user, slug):
    return (
        WorkspaceMember.objects.filter(workspace__slug=slug, member=user, is_active=True)
        .values_list("role", flat=True)
        .first()
    )


def collection_access(user, collection, role=None):
    """The caller's level on ``collection``; pass ``role`` when already known."""
    if role is None:
        role = workspace_role(user, collection.workspace.slug)
    if role is None:
        return NONE
    if collection.owned_by_id == user.id:
        return EDIT
    explicit = (
        WikiCollectionMember.objects.filter(collection=collection, member=user)
        .values_list("access", flat=True)
        .first()
    )
    if collection.access == WikiCollection.PRIVATE_ACCESS:
        return NONE if explicit is None else explicit
    granted = EDIT if role >= ROLE.MEMBER.value else NONE
    return max(granted, NONE if explicit is None else explicit)


def can_manage_collection(user, collection, role=None):
    """Rename, reorder, delete and change membership: the owner, or a workspace admin on a public collection."""
    if collection.owned_by_id == user.id:
        return True
    if role is None:
        role = workspace_role(user, collection.workspace.slug)
    return collection.access == WikiCollection.PUBLIC_ACCESS and role == ROLE.ADMIN.value


def visible_collections(user, slug) -> QuerySet:
    role = workspace_role(user, slug)
    base = WikiCollection.objects.filter(workspace__slug=slug)
    if role is None:
        return base.none()
    membership = WikiCollectionMember.objects.filter(collection=OuterRef("pk"), member=user)
    mine = Q(owned_by=user) | Q(Exists(membership))
    if role >= ROLE.MEMBER.value:
        return base.filter(Q(access=WikiCollection.PUBLIC_ACCESS) | mine)
    return base.filter(mine)


def wiki_pages(slug) -> QuerySet:
    """Every wiki page of the workspace, before any access filtering."""
    return Page.objects.filter(workspace__slug=slug, is_global=True, projects__isnull=True)


def visible_pages(user, slug) -> QuerySet:
    """Wiki pages the caller may read."""
    role = workspace_role(user, slug)
    if role is None:
        return Page.objects.none()
    filed = WikiPageCollection.objects.filter(page=OuterRef("pk"))
    in_visible = WikiPageCollection.objects.filter(
        page=OuterRef("pk"), collection__in=visible_collections(user, slug)
    )
    unfiled_ok = Q(~Exists(filed)) if role >= ROLE.MEMBER.value else Q(pk__in=[])
    return (
        wiki_pages(slug)
        .filter(Q(Exists(in_visible)) | unfiled_ok)
        .filter(Q(access=Page.PUBLIC_ACCESS) | Q(owned_by=user))
    )


def page_collection_row(page):
    return WikiPageCollection.objects.filter(page=page).select_related("collection", "collection__workspace").first()


def page_access(user, page, role=None):
    """The caller's level on a wiki page."""
    if role is None:
        role = workspace_role(user, page.workspace.slug)
    if role is None:
        return NONE
    if page.access == Page.PRIVATE_ACCESS and page.owned_by_id != user.id:
        return NONE
    row = page_collection_row(page)
    if row is None:
        level = EDIT if role >= ROLE.MEMBER.value else NONE
    else:
        level = collection_access(user, row.collection, role)
    if page.owned_by_id == user.id and level >= VIEW:
        return EDIT
    return level
