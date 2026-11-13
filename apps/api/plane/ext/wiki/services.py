# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Wiki operations shared by the web app and the API-key endpoints."""

# Python imports
import base64
import logging
import os
from datetime import datetime

# Third party imports
import requests

# Django imports
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Max

# Module imports
from plane.app.views.page.base import unarchive_archive_page_and_descendants
from plane.bgtasks.page_transaction_task import page_transaction
from plane.db.models import Page, UserFavorite, UserRecentVisit, Workspace
from plane.ext.models import WikiCollection, WikiPageCollection
from plane.utils.content_validator import validate_html_content

logger = logging.getLogger("plane.ext.wiki")

SORT_STEP = 10000
LIVE_TIMEOUT_SECONDS = 10


class WikiError(Exception):
    """A request the wiki refuses; ``status`` is the HTTP status to answer with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def default_collection(workspace: Workspace, user) -> WikiCollection:
    """The workspace's default collection, created the first time it is needed."""
    found = WikiCollection.objects.filter(workspace=workspace, is_default=True).first()
    if found:
        return found
    try:
        with transaction.atomic():
            return WikiCollection.objects.create(
                workspace=workspace,
                name="General",
                access=WikiCollection.PUBLIC_ACCESS,
                owned_by=workspace.owner or user,
                is_default=True,
                sort_order=0,
            )
    except IntegrityError:
        # A concurrent first visit created it; the unique constraint keeps one.
        return WikiCollection.objects.get(workspace=workspace, is_default=True)


def descendant_ids(page_id):
    """Ids of ``page_id`` and every page below it."""
    sql = """
    WITH RECURSIVE descendants AS (
        SELECT id FROM pages WHERE id = %s
        UNION
        SELECT pages.id FROM pages, descendants
        WHERE pages.parent_id = descendants.id AND pages.deleted_at IS NULL
    )
    SELECT id FROM descendants;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [str(page_id)])
        return [row[0] for row in cursor.fetchall()]


def next_sort_order(collection=None, parent=None, workspace=None):
    if parent is not None:
        top = Page.objects.filter(parent=parent).aggregate(top=Max("sort_order"))["top"]
    else:
        top = (
            WikiPageCollection.objects.filter(collection=collection, page__parent__isnull=True)
            .aggregate(top=Max("sort_order"))["top"]
            if collection is not None
            else None
        )
    return (top or 0) + SORT_STEP


def file_tree(root: Page, collection: WikiCollection | None, sort_order=None):
    """File ``root`` and its whole subtree into ``collection`` (``None`` unfiles them)."""
    ids = descendant_ids(root.id)
    WikiPageCollection.objects.filter(page_id__in=ids).delete(soft=False)
    if collection is None:
        return None
    rows = [
        WikiPageCollection(
            workspace_id=root.workspace_id,
            collection=collection,
            page_id=page_id,
            sort_order=sort_order if page_id == root.id and sort_order is not None else 65535,
        )
        for page_id in ids
    ]
    WikiPageCollection.objects.bulk_create(rows)
    return WikiPageCollection.objects.get(page=root)


def sanitize_html(value):
    if not value:
        return "<p></p>"
    is_valid, error_message, sanitized = validate_html_content(value)
    if not is_valid:
        raise WikiError(error_message or "The page content is not valid HTML.")
    return sanitized if sanitized is not None else value


def create_page(*, workspace, user, data, parent=None, collection=None) -> Page:
    """Create a wiki page under ``parent`` or filed in ``collection``."""
    html = sanitize_html(data.get("description_html"))
    with transaction.atomic():
        page = Page.objects.create(
            workspace=workspace,
            name=(data.get("name") or "").strip(),
            description_html=html,
            description_binary=None,
            access=data.get("access", Page.PUBLIC_ACCESS),
            color=data.get("color") or "",
            is_locked=bool(data.get("is_locked", False)),
            logo_props=data.get("logo_props") or {},
            view_props=data.get("view_props") or {"full_width": False},
            parent=parent,
            is_global=True,
            owned_by=user,
            external_id=data.get("external_id"),
            external_source=data.get("external_source"),
            sort_order=next_sort_order(collection=collection, parent=parent),
        )
        if parent is not None:
            row = WikiPageCollection.objects.filter(page=parent).first()
            if row is not None:
                WikiPageCollection.objects.create(workspace=workspace, collection=row.collection, page=page)
        elif collection is not None:
            WikiPageCollection.objects.create(
                workspace=workspace,
                collection=collection,
                page=page,
                sort_order=page.sort_order,
            )
    page_transaction.delay(new_description_html=html, old_description_html=None, page_id=page.id)
    return page


def move_page(page: Page, *, parent=..., collection=..., sort_order=None):
    """Re-parent and/or re-file a page; its subtree follows.

    ``...`` leaves a dimension alone. Moving under a parent files the page into
    the parent's collection; moving to the top level of a collection detaches it
    from its parent.
    """
    with transaction.atomic():
        if parent is not ... and parent is not None:
            # Serialize concurrent moves of the same pages so two requests cannot
            # each pass the cycle check and together create a loop.
            list(Page.objects.select_for_update().filter(pk__in=[page.id, parent.id]).order_by("pk"))
            if parent.archived_at:
                raise WikiError("A page cannot be moved under an archived page.")
        if parent is not ...:
            if parent is not None:
                if parent.id in descendant_ids(page.id):
                    raise WikiError("A page cannot be moved under itself or one of its children.")
                parent_row = WikiPageCollection.objects.filter(page=parent).first()
                collection = parent_row.collection if parent_row else None
            page.parent = parent
        elif collection is not ...:
            page.parent = None
        if sort_order is not None:
            page.sort_order = sort_order
        page.save(update_fields=["parent", "sort_order", "updated_at"])
        if collection is not ...:
            file_tree(page, collection, sort_order=sort_order if page.parent_id is None else None)
        elif sort_order is not None:
            WikiPageCollection.objects.filter(page=page).update(sort_order=sort_order)
    return page


def archive_page(page: Page):
    UserFavorite.objects.filter(entity_type="page", entity_identifier=page.id).delete()
    unarchive_archive_page_and_descendants(page.id, datetime.now())


def unarchive_page(page: Page):
    if page.parent_id and page.parent.archived_at:
        page.parent = None
        page.save(update_fields=["parent"])
    unarchive_archive_page_and_descendants(page.id, None)


def delete_page(page: Page):
    if page.archived_at is None:
        raise WikiError("The page should be archived before deleting.")
    with transaction.atomic():
        Page.objects.filter(parent_id=page.id).update(parent=None)
        WikiPageCollection.objects.filter(page=page).delete(soft=False)
    # Outside the transaction: delete() queues a task that soft-deletes related
    # rows, children included, and it must see them already detached.
    page.delete()
    UserFavorite.objects.filter(entity_type="page", entity_identifier=page.id).delete()
    UserRecentVisit.objects.filter(entity_name="page", entity_identifier=page.id).delete(soft=False)


def _live_url():
    url = os.environ.get("HANGAR_LIVE_INTERNAL_URL") or settings.LIVE_URL
    return url.rstrip("/") if url else None


def _live_post(path, payload):
    url, secret = _live_url(), settings.LIVE_SERVER_SECRET_KEY
    if not url or not secret:
        return None
    response = requests.post(
        f"{url}/{path.lstrip('/')}",
        json=payload,
        headers={"live-server-secret-key": secret},
        timeout=LIVE_TIMEOUT_SECONDS,
        allow_redirects=False,
    )
    response.raise_for_status()
    return response.json()


def write_content(page: Page, *, name=None, description_html=None):
    """Replace a page's title and/or body the way an editor would.

    The live server owns an open document. When someone has the page open, the
    change is applied inside that document so every editor receives it and the
    regular save writes it back; writing the database underneath would be
    overwritten by the next save, or merged into a duplicate by a reconnecting
    client. When nobody has it open, the database is written directly.
    """
    if page.is_locked:
        raise WikiError("The page is locked.")
    if page.archived_at:
        raise WikiError("The page is archived.")
    html = sanitize_html(description_html) if description_html is not None else None
    old_html = page.description_html

    try:
        applied = _live_post(
            "documents/replace/",
            {
                "document_name": str(page.id),
                **({"description_html": html} if html is not None else {}),
                **({"name": name} if name is not None else {}),
            },
        )
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            raise WikiError("The page is being closed by its last editor; retry in a few seconds.", status=409)
        logger.warning("Live server refused the write to page %s: %s", page.id, exc)
        raise WikiError("The collaboration service could not apply the change; nothing was written.", status=502)
    except requests.RequestException as exc:
        logger.warning("Live server unreachable while writing page %s: %s", page.id, exc)
        raise WikiError("The collaboration service is unavailable; nothing was written.", status=502)

    if applied and applied.get("applied"):
        # The live server saves the body through the regular description endpoint;
        # the title is mirrored here, and the body only in memory, so the response
        # is current right away.
        if name is not None:
            page.name = name
            page.save(update_fields=["name", "updated_at"])
        if html is not None:
            page.description_html = html
        return page

    fields = ["updated_at"]
    if name is not None:
        page.name = name
        fields.append("name")
        if html is None:
            # The stored document carries the old title; rebuild it from HTML and name.
            page.description_binary = None
            fields.append("description_binary")
    if html is not None:
        converted = {}
        try:
            converted = _live_post("convert-document/", {"description_html": html, "variant": "document"}) or {}
        except requests.RequestException as exc:
            logger.warning("Live conversion failed for page %s: %s", page.id, exc)
        page.description_html = html
        # Without a converted binary the stored one is dropped, and the live
        # server rebuilds the document from this HTML when it is next opened.
        page.description_binary = (
            base64.b64decode(converted["description_binary"])
            if converted.get("description_binary")
            else None
        )
        page.description_json = converted.get("description_json") or {}
        fields += ["description_html", "description_binary", "description_json", "description_stripped"]
    page.save(update_fields=fields)
    if html is not None:
        page_transaction.delay(new_description_html=html, old_description_html=old_html, page_id=page.id)
    return page
