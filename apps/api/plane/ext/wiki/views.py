# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Wiki endpoints.

Two front doors share one implementation: ``App*`` views answer the web app
(session auth, under ``/api/workspaces/<slug>/wiki/``) and ``Api*`` views
answer API keys (under ``/api/v1/workspaces/<slug>/``) with the paths, verbs
and payloads of the commercial edition's public API.
"""

# Python imports
import json
import uuid

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import StreamingHttpResponse

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView as ApiKeyBaseView
from plane.app.permissions import ROLE
from plane.app.serializers import PageBinaryUpdateSerializer
from plane.app.serializers.page import PageVersionDetailSerializer, PageVersionSerializer
from plane.app.views.base import BaseAPIView as SessionBaseView
from plane.bgtasks.page_transaction_task import page_transaction
from plane.bgtasks.page_version_task import track_page_version
from plane.bgtasks.recent_visited_task import recent_visited_task
from plane.db.models import Page, PageVersion, UserFavorite, Workspace, WorkspaceMember
from plane.ext.models import WikiCollection, WikiCollectionMember, WikiPageCollection
from plane.ext.wiki import access as policy
from plane.ext.wiki import services
from plane.ext.wiki.serializers import (
    WikiAppPageListSerializer,
    WikiAppPageSerializer,
    WikiCollectionMemberSerializer,
    WikiCollectionPageSerializer,
    WikiCollectionSerializer,
    WikiPageListSerializer,
    WikiPageSerializer,
)
from plane.utils.error_codes import ERROR_CODES

PAGE_EDITABLE_FIELDS = ("name", "color", "logo_props", "view_props", "external_id", "external_source")
NOT_FOUND = {"error": "Page not found."}
COLLECTION_NOT_FOUND = {"error": "Collection not found."}


def _bool(value):
    return str(value).lower() in ("1", "true", "yes")


def _uuid(value):
    """The canonical form of a UUID, or None when ``value`` is not one."""
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _bad(message):
    return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)


class WikiMixin:
    """Lookups and policy checks common to both front doors."""

    def wiki_role(self, slug):
        if not hasattr(self, "_wiki_role"):
            self._wiki_role = policy.workspace_role(self.request.user, slug)
        return self._wiki_role

    def workspace(self, slug):
        return Workspace.objects.get(slug=slug)

    def collection_for(self, slug, collection_id, level=policy.VIEW):
        collection = (
            WikiCollection.objects.filter(workspace__slug=slug, pk=collection_id).select_related("workspace").first()
        )
        if collection is None:
            return None, None
        granted = policy.collection_access(self.request.user, collection, self.wiki_role(slug))
        if granted < level:
            return None, granted
        return collection, granted

    def page_for(self, slug, page_id, level=policy.VIEW):
        page = policy.wiki_pages(slug).filter(pk=page_id).select_related("workspace").first()
        if page is None:
            return None, policy.NONE
        granted = policy.page_access(self.request.user, page, self.wiki_role(slug))
        if granted < level:
            return None, granted
        return page, granted

    def denied(self, granted, message):
        # Unknown and invisible look the same; visible but read-only says why.
        if granted is None or granted < policy.VIEW:
            return Response(message, status=status.HTTP_404_NOT_FOUND)
        return Response({"error": "You do not have edit access here."}, status=status.HTTP_403_FORBIDDEN)

    def refuse(self, error: services.WikiError):
        return Response({"error": error.message}, status=error.status)

    def leaving_private_refused(self, page, target_collection_id):
        """Taking a page out of a private collection would publish it; only the collection's manager may.

        ``target_collection_id`` is where the page ends up (None when unfiled).
        """
        row = policy.page_collection_row(page)
        if row is None or row.collection.access != WikiCollection.PRIVATE_ACCESS:
            return None
        if target_collection_id is not None and str(target_collection_id) == str(row.collection_id):
            return None
        if policy.can_manage_collection(self.request.user, row.collection, self.wiki_role(page.workspace.slug)):
            return None
        return Response(
            {"error": "Only the collection's owner can move pages out of a private collection."},
            status=status.HTTP_403_FORBIDDEN,
        )

    def collection_levels(self, slug, collections):
        role = self.wiki_role(slug)
        return {c.id: policy.collection_access(self.request.user, c, role) for c in collections}

    def resolve_create_target(self, slug, data):
        """The (parent, collection) a new page goes into, or a refusal Response."""
        parent_id = data.get("parent_id") or data.get("parent")
        collection_id = data.get("collection_id")
        if (parent_id and not _uuid(parent_id)) or (collection_id and not _uuid(collection_id)):
            return None, None, _bad("parent_id and collection_id must be UUIDs.")
        if parent_id and collection_id:
            return None, None, Response(
                {"error": "Pass parent_id or collection_id, not both. A nested page takes its parent's collection."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if parent_id:
            parent, granted = self.page_for(slug, parent_id, policy.EDIT)
            if parent is None:
                return None, None, self.denied(granted, {"error": "Parent page not found."})
            return parent, None, None
        if collection_id:
            collection, granted = self.collection_for(slug, collection_id, policy.EDIT)
            if collection is None:
                return None, None, self.denied(granted, COLLECTION_NOT_FOUND)
            return None, collection, None
        if self.wiki_role(slug) is None or self.wiki_role(slug) < ROLE.MEMBER.value:
            return None, None, Response(
                {"error": "Guests can only create pages in collections they are members of."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None, services.default_collection(self.workspace(slug), self.request.user), None

    def validate_access_value(self, data):
        if "access" not in data:
            return None
        if data["access"] not in (Page.PUBLIC_ACCESS, Page.PRIVATE_ACCESS):
            return Response({"error": "access must be 0 (public) or 1 (private)."}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def create_page(self, slug, data):
        if not isinstance(data.get("name") or "", str):
            return None, _bad("name must be a string.")
        if not isinstance(data.get("description_html") or "", str):
            return None, _bad("description_html must be a string.")
        error = self.validate_access_value(data)
        if error:
            return None, error
        parent, collection, error = self.resolve_create_target(slug, data)
        if error:
            return None, error
        try:
            page = services.create_page(
                workspace=self.workspace(slug), user=self.request.user, data=data, parent=parent, collection=collection
            )
        except services.WikiError as exc:
            return None, self.refuse(exc)
        return page, None

    def update_page_properties(self, page, data):
        """Apply property changes other than the body; returns a refusal Response or None."""
        error = self.validate_access_value(data)
        if error:
            return error
        if "access" in data and data["access"] != page.access and page.owned_by_id != self.request.user.id:
            return Response(
                {"error": "Access cannot be updated since this page is owned by someone else"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "is_locked" in data and page.owned_by_id != self.request.user.id and self.wiki_role(
            page.workspace.slug
        ) != ROLE.ADMIN.value:
            return Response({"error": "Only the owner or an admin can lock a page."}, status=status.HTTP_403_FORBIDDEN)
        fields = []
        for field in PAGE_EDITABLE_FIELDS:
            if field in data and field != "name":
                setattr(page, field, data[field] if data[field] is not None else getattr(page, field))
                fields.append(field)
        for field in ("access", "is_locked"):
            if field in data:
                setattr(page, field, data[field])
                fields.append(field)
        if fields:
            page.save(update_fields=fields + ["updated_at"])
        return None

    def can_delete(self, page, slug):
        if page.owned_by_id == self.request.user.id or self.wiki_role(slug) == ROLE.ADMIN.value:
            return True
        row = policy.page_collection_row(page)
        return bool(row and policy.can_manage_collection(self.request.user, row.collection, self.wiki_role(slug)))

    def visible_page_list(self, slug, request):
        queryset = policy.visible_pages(request.user, slug)
        archived = request.query_params.get("archived")
        if archived is not None:
            queryset = queryset.filter(archived_at__isnull=not _bool(archived))
        collection_id = request.query_params.get("collection_id")
        if collection_id:
            queryset = (
                queryset.filter(wiki_page_collections__collection_id=_uuid(collection_id))
                if _uuid(collection_id)
                else queryset.none()
            )
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        favorites = UserFavorite.objects.filter(
            user=request.user, entity_type="page", entity_identifier=OuterRef("pk"), workspace__slug=slug
        )
        return (
            queryset.annotate(is_favorite=Exists(favorites))
            .annotate(
                # Only children the caller can see; children share their parent's collection.
                sub_pages_count=Count(
                    "child_page",
                    filter=Q(child_page__archived_at__isnull=True, child_page__deleted_at__isnull=True)
                    & (Q(child_page__access=Page.PUBLIC_ACCESS) | Q(child_page__owned_by=request.user)),
                )
            )
            .order_by("sort_order", "created_at")
        )


# --------------------------------------------------------------------------- #
# Collections                                                                 #
# --------------------------------------------------------------------------- #


class CollectionsMixin(WikiMixin):
    def list_collections(self, request, slug):
        collections = list(
            policy.visible_collections(request.user, slug)
            .annotate(
                has_pages=Exists(
                    WikiPageCollection.objects.filter(collection=OuterRef("pk"), page__archived_at__isnull=True)
                )
            )
            .order_by("-is_default", "sort_order", "created_at")
        )
        if self.wiki_role(slug) is not None and not any(c.is_default for c in collections):
            if self.wiki_role(slug) >= ROLE.MEMBER.value:
                collections.insert(0, services.default_collection(self.workspace(slug), request.user))
        context = {"access_levels": self.collection_levels(slug, collections)}
        return Response(WikiCollectionSerializer(collections, many=True, context=context).data)

    def create_collection(self, request, slug):
        if self.wiki_role(slug) is None or self.wiki_role(slug) < ROLE.MEMBER.value:
            return Response({"error": "Only workspace members can create collections."}, status=status.HTTP_403_FORBIDDEN)
        name = request.data.get("name") or ""
        if not isinstance(name, str) or not name.strip():
            return Response({"name": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        name = name.strip()
        access = request.data.get("access", WikiCollection.PUBLIC_ACCESS)
        if access not in (WikiCollection.PUBLIC_ACCESS, WikiCollection.PRIVATE_ACCESS):
            return Response({"error": "access must be 0 (public) or 1 (private)."}, status=status.HTTP_400_BAD_REQUEST)
        last = WikiCollection.objects.filter(workspace__slug=slug).order_by("-sort_order").first()
        collection = WikiCollection.objects.create(
            workspace=self.workspace(slug),
            name=name[:255],
            access=access,
            logo_props=request.data.get("logo_props") or {},
            owned_by=request.user,
            sort_order=(last.sort_order if last else 0) + services.SORT_STEP,
        )
        context = {"access_levels": {collection.id: policy.EDIT}}
        return Response(WikiCollectionSerializer(collection, context=context).data, status=status.HTTP_201_CREATED)

    def retrieve_collection(self, request, slug, collection_id):
        collection, granted = self.collection_for(slug, collection_id)
        if collection is None:
            return self.denied(granted, COLLECTION_NOT_FOUND)
        context = {"access_levels": {collection.id: granted}}
        return Response(WikiCollectionSerializer(collection, context=context).data)

    def update_collection(self, request, slug, collection_id):
        collection, granted = self.collection_for(slug, collection_id)
        if collection is None:
            return self.denied(granted, COLLECTION_NOT_FOUND)
        if not policy.can_manage_collection(request.user, collection, self.wiki_role(slug)):
            return Response({"error": "Only the owner can change this collection."}, status=status.HTTP_403_FORBIDDEN)
        if "access" in request.data and request.data["access"] != collection.access:
            return Response(
                {"error": "A collection's access cannot be changed after it is created."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fields = []
        if "name" in request.data:
            name = request.data.get("name") or ""
            if not isinstance(name, str) or not name.strip():
                return Response({"name": ["This field may not be blank."]}, status=status.HTTP_400_BAD_REQUEST)
            collection.name = name.strip()[:255]
            fields.append("name")
        if request.data.get("logo_props") is not None:
            if not isinstance(request.data["logo_props"], dict):
                return _bad("logo_props must be an object.")
            collection.logo_props = request.data["logo_props"]
            fields.append("logo_props")
        if request.data.get("sort_order") is not None:
            if _number(request.data["sort_order"]) is None:
                return _bad("sort_order must be a number.")
            collection.sort_order = _number(request.data["sort_order"])
            fields.append("sort_order")
        if fields:
            collection.save(update_fields=fields + ["updated_at"])
        context = {"access_levels": {collection.id: granted}}
        return Response(WikiCollectionSerializer(collection, context=context).data)

    def delete_collection(self, request, slug, collection_id):
        collection, granted = self.collection_for(slug, collection_id)
        if collection is None:
            return self.denied(granted, COLLECTION_NOT_FOUND)
        if collection.is_default:
            return Response({"error": "The default collection cannot be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        if not policy.can_manage_collection(request.user, collection, self.wiki_role(slug)):
            return Response({"error": "Only the owner can delete this collection."}, status=status.HTTP_403_FORBIDDEN)
        archive = request.query_params.get("archive_pages")
        archive = True if archive is None else _bool(archive)
        private = collection.access == WikiCollection.PRIVATE_ACCESS
        with transaction.atomic():
            rows = WikiPageCollection.objects.filter(collection=collection)
            page_ids = list(rows.values_list("page_id", flat=True))
            if private:
                # Pages written for the collection's members must not surface
                # anywhere else: each becomes private to its own author, archived.
                Page.objects.filter(pk__in=page_ids).update(access=Page.PRIVATE_ACCESS)
            if archive or private:
                for root in Page.objects.filter(pk__in=page_ids, parent__isnull=True):
                    services.archive_page(root)
            # Refile into the default collection; an unfiled page would fall
            # under the looser rule for pages outside any collection.
            rows.delete(soft=False)
            if page_ids:
                default = services.default_collection(collection.workspace, request.user)
                WikiPageCollection.objects.bulk_create(
                    [WikiPageCollection(workspace=collection.workspace, collection=default, page_id=pid) for pid in page_ids]
                )
            WikiCollectionMember.objects.filter(collection=collection).delete(soft=False)
            collection.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CollectionMembersMixin(WikiMixin):
    def managed_collection(self, request, slug, collection_id):
        collection, granted = self.collection_for(slug, collection_id)
        if collection is None:
            return None, self.denied(granted, COLLECTION_NOT_FOUND)
        return collection, None

    def list_members(self, request, slug, collection_id):
        collection, error = self.managed_collection(request, slug, collection_id)
        if error:
            return error
        members = WikiCollectionMember.objects.filter(collection=collection)
        return Response(WikiCollectionMemberSerializer(members, many=True).data)

    def add_member(self, request, slug, collection_id):
        collection, error = self.managed_collection(request, slug, collection_id)
        if error:
            return error
        if not policy.can_manage_collection(request.user, collection, self.wiki_role(slug)):
            return Response({"error": "Only the owner can change members."}, status=status.HTTP_403_FORBIDDEN)
        member_id = _uuid(request.data.get("member"))
        access = request.data.get("access")
        if member_id is None:
            return _bad("member must be a user id.")
        if access not in (policy.VIEW, policy.COMMENT, policy.EDIT):
            return Response({"error": "access must be 0, 1 or 2."}, status=status.HTTP_400_BAD_REQUEST)
        if not WorkspaceMember.objects.filter(workspace__slug=slug, member_id=member_id, is_active=True).exists():
            return Response({"error": "That user is not a member of this workspace."}, status=status.HTTP_400_BAD_REQUEST)
        member, _ = WikiCollectionMember.objects.update_or_create(
            collection=collection,
            member_id=member_id,
            defaults={"access": access, "workspace": collection.workspace},
        )
        return Response(WikiCollectionMemberSerializer(member).data, status=status.HTTP_201_CREATED)

    def change_member(self, request, slug, collection_id, member_id, remove=False):
        collection, error = self.managed_collection(request, slug, collection_id)
        if error:
            return error
        if not policy.can_manage_collection(request.user, collection, self.wiki_role(slug)):
            return Response({"error": "Only the owner can change members."}, status=status.HTTP_403_FORBIDDEN)
        member = WikiCollectionMember.objects.filter(collection=collection, pk=member_id).first()
        if member is None:
            return Response({"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND)
        if remove:
            member.delete(soft=False)
            return Response(status=status.HTTP_204_NO_CONTENT)
        access = request.data.get("access")
        if access not in (policy.VIEW, policy.COMMENT, policy.EDIT):
            return Response({"error": "access must be 0, 1 or 2."}, status=status.HTTP_400_BAD_REQUEST)
        member.access = access
        member.save(update_fields=["access", "updated_at"])
        return Response(WikiCollectionMemberSerializer(member).data)


# --------------------------------------------------------------------------- #
# Web app (session)                                                           #
# --------------------------------------------------------------------------- #


class AppCollectionsEndpoint(CollectionsMixin, SessionBaseView):
    def get(self, request, slug):
        return self.list_collections(request, slug)

    def post(self, request, slug):
        return self.create_collection(request, slug)


class AppCollectionDetailEndpoint(CollectionsMixin, SessionBaseView):
    def get(self, request, slug, collection_id):
        return self.retrieve_collection(request, slug, collection_id)

    def patch(self, request, slug, collection_id):
        return self.update_collection(request, slug, collection_id)

    def delete(self, request, slug, collection_id):
        return self.delete_collection(request, slug, collection_id)


class AppCollectionMembersEndpoint(CollectionMembersMixin, SessionBaseView):
    def get(self, request, slug, collection_id):
        return self.list_members(request, slug, collection_id)

    def post(self, request, slug, collection_id):
        return self.add_member(request, slug, collection_id)


class AppCollectionMemberDetailEndpoint(CollectionMembersMixin, SessionBaseView):
    def patch(self, request, slug, collection_id, member_id):
        return self.change_member(request, slug, collection_id, member_id)

    def delete(self, request, slug, collection_id, member_id):
        return self.change_member(request, slug, collection_id, member_id, remove=True)


class AppPagesEndpoint(WikiMixin, SessionBaseView):
    def get(self, request, slug):
        if self.wiki_role(slug) is None:
            return Response({"error": "You are not a member of this workspace."}, status=status.HTTP_403_FORBIDDEN)
        pages = self.visible_page_list(slug, request).prefetch_related("wiki_page_collections")
        return Response(WikiAppPageListSerializer(_with_rows(pages), many=True).data)

    def post(self, request, slug):
        data = dict(request.data)
        data.setdefault("description_html", "<p></p>")
        page, error = self.create_page(slug, data)
        if error:
            return error
        return Response(WikiAppPageSerializer(page).data, status=status.HTTP_201_CREATED)


class AppPageDetailEndpoint(WikiMixin, SessionBaseView):
    def get(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        if request.query_params.get("track_visit", "true").lower() == "true":
            recent_visited_task.delay(
                slug=slug, entity_name="page", entity_identifier=page_id, user_id=request.user.id, project_id=None
            )
        data = WikiAppPageSerializer(page).data
        data["current_user_access"] = granted
        return Response(data)

    def patch(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        if page.is_locked and set(request.data) - {"is_locked"}:
            return Response({"error": "Page is locked"}, status=status.HTTP_400_BAD_REQUEST)
        error = self.update_page_properties(page, request.data)
        if error:
            return error
        if "name" in request.data:
            # The editor owns the title through the live document; this only
            # mirrors it, as the project page endpoint does.
            page.name = request.data.get("name") or ""
            page.save(update_fields=["name", "updated_at"])
        return Response(WikiAppPageSerializer(page).data)

    def delete(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        if not self.can_delete(page, slug):
            return Response({"error": "Only admin or owner can delete the page"}, status=status.HTTP_403_FORBIDDEN)
        try:
            services.delete_page(page)
        except services.WikiError as exc:
            return self.refuse(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppPageArchiveEndpoint(WikiMixin, SessionBaseView):
    def post(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        services.archive_page(page)
        page.refresh_from_db()
        return Response({"archived_at": str(page.archived_at)}, status=status.HTTP_200_OK)

    def delete(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        services.unarchive_page(page)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppPageLockEndpoint(WikiMixin, SessionBaseView):
    def post(self, request, slug, page_id):
        return self._set(request, slug, page_id, True)

    def delete(self, request, slug, page_id):
        return self._set(request, slug, page_id, False)

    def _set(self, request, slug, page_id, locked):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        error = self.update_page_properties(page, {"is_locked": locked})
        return error or Response(status=status.HTTP_204_NO_CONTENT)


class AppPageMoveEndpoint(WikiMixin, SessionBaseView):
    """Drag and drop in the sidebar: new parent, new collection, new position."""

    def post(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        sort_order = request.data.get("sort_order")
        if sort_order is not None and _number(sort_order) is None:
            return _bad("sort_order must be a number.")
        kwargs = {"sort_order": _number(sort_order)}
        parent_id, collection_id = request.data.get("parent_id"), request.data.get("collection_id")
        if (parent_id and not _uuid(parent_id)) or (collection_id and not _uuid(collection_id)):
            return _bad("parent_id and collection_id must be UUIDs.")
        target = ...
        if parent_id:
            parent, parent_granted = self.page_for(slug, parent_id, policy.EDIT)
            if parent is None:
                return self.denied(parent_granted, {"error": "Parent page not found."})
            kwargs["parent"] = parent
            parent_row = policy.page_collection_row(parent)
            target = parent_row.collection_id if parent_row else None
        elif collection_id:
            collection, c_granted = self.collection_for(slug, collection_id, policy.EDIT)
            if collection is None:
                return self.denied(c_granted, COLLECTION_NOT_FOUND)
            kwargs["collection"] = collection
            target = collection.id
        if target is not ...:
            refused = self.leaving_private_refused(page, target)
            if refused:
                return refused
        try:
            services.move_page(page, **kwargs)
        except services.WikiError as exc:
            return self.refuse(exc)
        return Response(WikiAppPageSerializer(page).data)


class AppPageDuplicateEndpoint(WikiMixin, SessionBaseView):
    def post(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        row = policy.page_collection_row(page)
        copy, error = self.create_page(
            slug,
            {
                "name": f"{page.name} (Copy)",
                "description_html": page.description_html,
                "access": page.access,
                "logo_props": page.logo_props,
                "view_props": page.view_props,
                **({"parent_id": str(page.parent_id)} if page.parent_id else {}),
                **({"collection_id": str(row.collection_id)} if row and not page.parent_id else {}),
            },
        )
        if error:
            return error
        return Response(WikiAppPageSerializer(copy).data, status=status.HTTP_201_CREATED)


class AppPageDescriptionEndpoint(WikiMixin, SessionBaseView):
    """The live server's load and save path for a wiki page body."""

    def get(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        binary = page.description_binary

        def stream():
            yield bytes(binary) if binary else b""

        response = StreamingHttpResponse(stream(), content_type="application/octet-stream")
        response["Content-Disposition"] = 'attachment; filename="page_description.bin"'
        return response

    def patch(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        if page.is_locked:
            return Response(
                {"error_code": ERROR_CODES["PAGE_LOCKED"], "error_message": "PAGE_LOCKED"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if page.archived_at:
            return Response(
                {"error_code": ERROR_CODES["PAGE_ARCHIVED"], "error_message": "PAGE_ARCHIVED"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        old_html = page.description_html
        existing_instance = json.dumps({"description_html": old_html}, cls=DjangoJSONEncoder)
        serializer = PageBinaryUpdateSerializer(page, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        page = serializer.save()
        if request.data.get("description_html"):
            page_transaction.delay(
                new_description_html=page.description_html or "<p></p>",
                old_description_html=old_html,
                page_id=page_id,
            )
        track_page_version.delay(page_id=page_id, existing_instance=existing_instance, user_id=request.user.id)
        return Response({"message": "Updated successfully"})


class AppPageVersionsEndpoint(WikiMixin, SessionBaseView):
    def get(self, request, slug, page_id, version_id=None):
        page, granted = self.page_for(slug, page_id)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        versions = PageVersion.objects.filter(workspace__slug=slug, page=page)
        if version_id:
            version = versions.filter(pk=version_id).first()
            if version is None:
                return Response({"error": "Version not found."}, status=status.HTTP_404_NOT_FOUND)
            return Response(PageVersionDetailSerializer(version).data)
        return Response(PageVersionSerializer(versions, many=True).data)


def _with_rows(pages):
    """Attach each page's filing row from the prefetch, so serializing a list stays one query."""
    pages = list(pages)
    for page in pages:
        rows = list(page.wiki_page_collections.all())
        page._wiki_row = rows[0] if rows else False
    return pages


# --------------------------------------------------------------------------- #
# Public API (API key)                                                        #
# --------------------------------------------------------------------------- #


class ApiWikiBase(WikiMixin, ApiKeyBaseView):
    pass


class ApiPagesEndpoint(ApiWikiBase):
    def get(self, request, slug):
        if self.wiki_role(slug) is None:
            return Response({"error": "You are not a member of this workspace."}, status=status.HTTP_403_FORBIDDEN)
        queryset = self.visible_page_list(slug, request)
        if request.query_params.get("archived") is None:
            queryset = queryset.filter(archived_at__isnull=True)
        return self.paginate(
            request=request,
            queryset=queryset.prefetch_related("wiki_page_collections"),
            on_results=lambda pages: WikiPageListSerializer(_with_rows(pages), many=True).data,
            default_per_page=100,
            max_per_page=100,
        )

    def post(self, request, slug):
        if not isinstance(request.data, dict):
            return _bad("Expected a JSON object.")
        data = dict(request.data)
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            return Response({"name": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        if data.get("description_html") is None:
            return Response({"description_html": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        page, error = self.create_page(slug, data)
        if error:
            return error
        return Response(WikiPageSerializer(page).data, status=status.HTTP_201_CREATED)


class ApiPageDetailEndpoint(ApiWikiBase):
    def get(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        return Response(WikiPageSerializer(page).data)

    def put(self, request, slug, page_id):
        return self._update(request, slug, page_id)

    def patch(self, request, slug, page_id):
        return self._update(request, slug, page_id)

    def _update(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        data = request.data
        if not isinstance(data, dict):
            return _bad("Expected a JSON object.")
        if page.is_locked and not (set(data) <= {"is_locked"}):
            return Response({"error": "Page is locked."}, status=status.HTTP_400_BAD_REQUEST)
        # Validate everything before changing anything, so a refusal leaves the page as it was.
        name = data.get("name") if "name" in data else None
        if name is not None and (not isinstance(name, str) or not name.strip()):
            return Response({"name": ["This field may not be blank."]}, status=status.HTTP_400_BAD_REQUEST)
        html = data.get("description_html") if "description_html" in data else None
        if html is not None and not isinstance(html, str):
            return _bad("description_html must be a string.")
        error = self.validate_access_value(data)
        if error:
            return error
        if "archived_at" in data:
            if data["archived_at"]:
                services.archive_page(page)
            else:
                services.unarchive_page(page)
            page.refresh_from_db()
        properties = {k: v for k, v in data.items() if k not in ("name", "description_html", "archived_at")}
        error = self.update_page_properties(page, properties)
        if error:
            return error
        if name is not None or html is not None:
            try:
                page = services.write_content(page, name=name, description_html=html)
            except services.WikiError as exc:
                return self.refuse(exc)
        return Response(WikiPageSerializer(page).data)

    def delete(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        if not self.can_delete(page, slug):
            return Response({"error": "Only admin or owner can delete the page"}, status=status.HTTP_403_FORBIDDEN)
        try:
            services.delete_page(page)
        except services.WikiError as exc:
            return self.refuse(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApiPageArchiveEndpoint(ApiWikiBase):
    def post(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        services.archive_page(page)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, slug, page_id):
        page, granted = self.page_for(slug, page_id, policy.EDIT)
        if page is None:
            return self.denied(granted, NOT_FOUND)
        services.unarchive_page(page)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApiCollectionsEndpoint(CollectionsMixin, ApiKeyBaseView):
    def get(self, request, slug):
        return self.list_collections(request, slug)

    def post(self, request, slug):
        return self.create_collection(request, slug)


class ApiCollectionDetailEndpoint(CollectionsMixin, ApiKeyBaseView):
    def get(self, request, slug, collection_id):
        return self.retrieve_collection(request, slug, collection_id)

    def patch(self, request, slug, collection_id):
        return self.update_collection(request, slug, collection_id)

    def delete(self, request, slug, collection_id):
        return self.delete_collection(request, slug, collection_id)


class ApiCollectionMembersEndpoint(CollectionMembersMixin, ApiKeyBaseView):
    def get(self, request, slug, collection_id):
        return self.list_members(request, slug, collection_id)

    def post(self, request, slug, collection_id):
        return self.add_member(request, slug, collection_id)


class ApiCollectionMemberDetailEndpoint(CollectionMembersMixin, ApiKeyBaseView):
    def patch(self, request, slug, collection_id, member_id):
        return self.change_member(request, slug, collection_id, member_id)

    def delete(self, request, slug, collection_id, member_id):
        return self.change_member(request, slug, collection_id, member_id, remove=True)


class ApiCollectionPagesEndpoint(ApiWikiBase):
    """Pages filed in a collection, one branch at a time."""

    def get(self, request, slug, collection_id):
        collection, granted = self.collection_for(slug, collection_id)
        if collection is None:
            return self.denied(granted, COLLECTION_NOT_FOUND)
        visible = policy.visible_pages(request.user, slug).filter(archived_at__isnull=True)
        rows = WikiPageCollection.objects.filter(collection=collection, page__in=visible).select_related("page")
        parent_id = request.query_params.get("parent_id")
        if parent_id and not _uuid(parent_id):
            return _bad("parent_id must be a UUID.")
        rows = rows.filter(page__parent_id=parent_id) if parent_id else rows.filter(page__parent__isnull=True)
        search = request.query_params.get("search")
        if search:
            rows = rows.filter(page__name__icontains=search)
        # The page's own sort order is the one the tree uses at every level.
        rows = rows.order_by("page__sort_order", "created_at")

        def branch(items):
            return [
                {
                    "page_collection_id": str(row.id),
                    "collection_id": str(row.collection_id),
                    "parent_id": str(row.page.parent_id) if row.page.parent_id else None,
                    "sort_order": row.sort_order,
                    "page": WikiPageListSerializer(_attach(row.page, row)).data,
                }
                for row in items
            ]

        return self.paginate(
            request=request, queryset=rows, on_results=branch, default_per_page=100, max_per_page=100
        )

    def post(self, request, slug, collection_id):
        collection, granted = self.collection_for(slug, collection_id, policy.EDIT)
        if collection is None:
            return self.denied(granted, COLLECTION_NOT_FOUND)
        page_ids = request.data.get("page_ids") or []
        if not isinstance(page_ids, list) or not page_ids:
            return Response({"page_ids": ["Pass at least one page id."]}, status=status.HTTP_400_BAD_REQUEST)
        sort_orders = request.data.get("sort_orders") or {}
        if not isinstance(sort_orders, dict) or any(_number(v) is None for v in sort_orders.values()):
            return _bad("sort_orders must map page ids to numbers.")
        if any(not _uuid(page_id) for page_id in page_ids):
            return _bad("page_ids must be UUIDs.")
        pages = []
        for page_id in page_ids:
            page, page_granted = self.page_for(slug, page_id, policy.EDIT)
            if page is None:
                return self.denied(page_granted, {"error": f"Page {page_id} not found."})
            if page.parent_id:
                return Response(
                    {"error": "Only top-level pages can be filed; a nested page follows its parent."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            refused = self.leaving_private_refused(page, collection.id)
            if refused:
                return refused
            pages.append(page)
        rows = []
        for page in pages:
            order = _number(sort_orders.get(str(page.id)))
            if order is None:
                order = services.next_sort_order(collection=collection)
            rows.append(services.file_tree(page, collection, sort_order=order))
            Page.objects.filter(pk=page.id).update(sort_order=order)
        return Response(WikiCollectionPageSerializer(rows, many=True).data, status=status.HTTP_201_CREATED)


class ApiCollectionPagesSearchEndpoint(ApiWikiBase):
    """Top-level pages the caller could file into this collection."""

    def get(self, request, slug, collection_id):
        collection, granted = self.collection_for(slug, collection_id, policy.EDIT)
        if collection is None:
            return self.denied(granted, COLLECTION_NOT_FOUND)
        pages = (
            policy.visible_pages(request.user, slug)
            .filter(parent__isnull=True, archived_at__isnull=True)
            .exclude(wiki_page_collections__collection=collection)
        )
        search = request.query_params.get("search")
        if search:
            pages = pages.filter(name__icontains=search)
        return Response([{"id": str(p.id), "name": p.name, "logo_props": p.logo_props} for p in pages[:50]])


class ApiCollectionPageDetailEndpoint(ApiWikiBase):
    def patch(self, request, slug, collection_id, page_collection_id):
        row, error = self._row(slug, collection_id, page_collection_id)
        if error:
            return error
        sort_order = request.data.get("sort_order")
        if sort_order is not None and _number(sort_order) is None:
            return _bad("sort_order must be a number.")
        sort_order = _number(sort_order)
        target_id = request.data.get("collection")
        if target_id and not _uuid(target_id):
            return _bad("collection must be a UUID.")
        if target_id and str(target_id) != str(row.collection_id):
            target, granted = self.collection_for(slug, target_id, policy.EDIT)
            if target is None:
                return self.denied(granted, COLLECTION_NOT_FOUND)
            root = row.page
            if root.parent_id:
                return Response(
                    {"error": "Move the top-level page; a nested page follows its parent."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            refused = self.leaving_private_refused(root, target.id)
            if refused:
                return refused
            order = sort_order if sort_order is not None else services.next_sort_order(target)
            row = services.file_tree(root, target, sort_order=order)
            Page.objects.filter(pk=root.id).update(sort_order=order)
        elif sort_order is not None:
            row.sort_order = sort_order
            row.save(update_fields=["sort_order", "updated_at"])
            Page.objects.filter(pk=row.page_id).update(sort_order=sort_order)
        return Response(WikiCollectionPageSerializer(row).data)

    def delete(self, request, slug, collection_id, page_collection_id):
        row, error = self._row(slug, collection_id, page_collection_id)
        if error:
            return error
        if row.page.parent_id:
            return Response(
                {"error": "Unfile the top-level page; a nested page follows its parent."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        refused = self.leaving_private_refused(row.page, None)
        if refused:
            return refused
        services.file_tree(row.page, None)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _row(self, slug, collection_id, page_collection_id):
        collection, granted = self.collection_for(slug, collection_id, policy.EDIT)
        if collection is None:
            return None, self.denied(granted, COLLECTION_NOT_FOUND)
        row = (
            WikiPageCollection.objects.filter(collection=collection, pk=page_collection_id).select_related("page").first()
        )
        if row is None:
            return None, Response({"error": "That page is not in this collection."}, status=status.HTTP_404_NOT_FOUND)
        page, page_granted = self.page_for(slug, row.page_id, policy.EDIT)
        if page is None:
            return None, self.denied(page_granted, NOT_FOUND)
        return row, None


def _attach(page, row):
    page._wiki_row = row
    return page
