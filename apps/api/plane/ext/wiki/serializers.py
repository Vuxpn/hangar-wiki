# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Response shapes for wiki collections and pages.

The API-key payloads follow the commercial edition's public contract field for
field (see the plane-sdk ``Page``/``Collection`` models), so the official SDK
and MCP server parse them unchanged. The web app gets the same fields plus the
ones its page store expects from project pages.
"""

# Third party imports
from rest_framework import serializers

# Module imports
from plane.app.serializers.base import BaseSerializer
from plane.db.models import Page
from plane.ext.models import WikiCollection, WikiCollectionMember, WikiPageCollection


class WikiCollectionSerializer(BaseSerializer):
    owned_by_id = serializers.UUIDField(read_only=True)
    is_global = serializers.SerializerMethodField()
    has_pages = serializers.SerializerMethodField()
    current_user_access = serializers.SerializerMethodField()

    class Meta:
        model = WikiCollection
        fields = [
            "id",
            "name",
            "owned_by_id",
            "access",
            "current_user_access",
            "has_pages",
            "is_default",
            "is_global",
            "logo_props",
            "sort_order",
            "workspace",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields

    def get_is_global(self, obj):
        return True

    def get_has_pages(self, obj):
        annotated = getattr(obj, "has_pages", None)
        if annotated is not None:
            return annotated
        return WikiPageCollection.objects.filter(collection=obj, page__archived_at__isnull=True).exists()

    def get_current_user_access(self, obj):
        levels = self.context.get("access_levels") or {}
        level = levels.get(obj.id)
        return None if level is None or level < 0 else level


class WikiCollectionMemberSerializer(BaseSerializer):
    class Meta:
        model = WikiCollectionMember
        fields = [
            "id",
            "collection",
            "member",
            "access",
            "workspace",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields


class WikiCollectionPageSerializer(BaseSerializer):
    """The flat membership row (``CollectionPage`` in the SDK)."""

    class Meta:
        model = WikiPageCollection
        fields = [
            "id",
            "collection",
            "page",
            "workspace",
            "sort_order",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields


def _filing(page):
    row = getattr(page, "_wiki_row", None)
    if row is None:
        row = WikiPageCollection.objects.filter(page=page).only("id", "collection_id").first()
        page._wiki_row = row or False
    return row or None


class WikiPageSerializer(BaseSerializer):
    """A wiki page as the public API returns it (the SDK's ``Page``)."""

    parent_id = serializers.UUIDField(read_only=True)
    projects = serializers.SerializerMethodField()
    collection_id = serializers.SerializerMethodField()
    page_collection_id = serializers.SerializerMethodField()
    owned_by = serializers.UUIDField(source="owned_by_id", read_only=True)
    anchor = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            "id",
            "name",
            "description_stripped",
            "description_html",
            "created_at",
            "updated_at",
            "owned_by",
            "anchor",
            "workspace",
            "projects",
            "access",
            "color",
            "is_locked",
            "archived_at",
            "parent_id",
            "collection_id",
            "page_collection_id",
            "logo_props",
            "view_props",
            "sort_order",
            "external_id",
            "external_source",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields

    def get_projects(self, obj):
        return []

    def get_anchor(self, obj):
        return None

    def get_collection_id(self, obj):
        row = _filing(obj)
        return str(row.collection_id) if row else None

    def get_page_collection_id(self, obj):
        row = _filing(obj)
        return str(row.id) if row else None


class WikiPageListSerializer(WikiPageSerializer):
    """Without the body, for lists."""

    class Meta(WikiPageSerializer.Meta):
        fields = [f for f in WikiPageSerializer.Meta.fields if f not in ("description_html", "description_stripped")]
        read_only_fields = fields


class WikiAppPageSerializer(WikiPageSerializer):
    """What the web app's page store reads, matching the project page payload."""

    parent = serializers.UUIDField(source="parent_id", read_only=True)
    is_favorite = serializers.SerializerMethodField()
    label_ids = serializers.SerializerMethodField()
    project_ids = serializers.SerializerMethodField()
    sub_pages_count = serializers.SerializerMethodField()

    class Meta(WikiPageSerializer.Meta):
        fields = WikiPageSerializer.Meta.fields + [
            "parent",
            "is_favorite",
            "label_ids",
            "project_ids",
            "sub_pages_count",
        ]
        read_only_fields = fields

    def get_is_favorite(self, obj):
        return bool(getattr(obj, "is_favorite", False))

    def get_label_ids(self, obj):
        return []

    def get_project_ids(self, obj):
        return []

    def get_sub_pages_count(self, obj):
        annotated = getattr(obj, "sub_pages_count", None)
        if annotated is not None:
            return annotated
        return Page.objects.filter(parent=obj, archived_at__isnull=True).count()


class WikiAppPageListSerializer(WikiAppPageSerializer):
    class Meta(WikiAppPageSerializer.Meta):
        fields = [f for f in WikiAppPageSerializer.Meta.fields if f not in ("description_html", "description_stripped")]
        read_only_fields = fields
