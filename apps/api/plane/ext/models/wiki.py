# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace wiki: collections that file workspace-level pages.

A wiki page is an upstream ``Page`` with ``is_global=True`` and no
``ProjectPage`` link, so the editor, versions, live collaboration and every
other page feature apply unchanged. What the fork adds is where a page is
filed (``WikiPageCollection``) and who may see a collection
(``WikiCollection.access`` plus ``WikiCollectionMember``).

Field names follow the public API contract of the commercial edition, so the
official SDK and MCP server work against these tables without changes.
"""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from plane.db.models.base import BaseModel


class WikiCollection(BaseModel):
    PUBLIC_ACCESS = 0
    PRIVATE_ACCESS = 1
    ACCESS_CHOICES = ((PUBLIC_ACCESS, "Public"), (PRIVATE_ACCESS, "Private"))
    DEFAULT_SORT_ORDER = 65535

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="wiki_collections")
    name = models.CharField(max_length=255)
    logo_props = models.JSONField(default=dict, blank=True)
    # Fixed at creation: widening a private collection would expose pages that
    # were written for its members only.
    access = models.PositiveSmallIntegerField(choices=ACCESS_CHOICES, default=PUBLIC_ACCESS)
    owned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_wiki_collections"
    )
    is_default = models.BooleanField(default=False)
    sort_order = models.FloatField(default=DEFAULT_SORT_ORDER)

    class Meta:
        verbose_name = "Wiki Collection"
        verbose_name_plural = "Wiki Collections"
        db_table = "ext_wiki_collections"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"],
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="ext_wiki_collection_one_default",
            ),
        ]

    def __str__(self):
        return f"{self.name} <{self.workspace_id}>"


class WikiCollectionMember(BaseModel):
    VIEW = 0
    COMMENT = 1
    EDIT = 2
    ACCESS_CHOICES = ((VIEW, "View"), (COMMENT, "Comment"), (EDIT, "Edit"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="wiki_collection_members")
    collection = models.ForeignKey(WikiCollection, on_delete=models.CASCADE, related_name="members")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wiki_collection_memberships"
    )
    access = models.PositiveSmallIntegerField(choices=ACCESS_CHOICES, default=VIEW)

    class Meta:
        verbose_name = "Wiki Collection Member"
        verbose_name_plural = "Wiki Collection Members"
        db_table = "ext_wiki_collection_members"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "member"],
                condition=Q(deleted_at__isnull=True),
                name="ext_wiki_collection_member_unique",
            ),
        ]


class WikiPageCollection(BaseModel):
    """Files one wiki page into one collection.

    Every page of a tree carries its own row, all naming the collection of the
    tree's root, so a nested page reports where it lives without walking up
    the hierarchy and access checks stay a single join.
    """

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="wiki_page_collections")
    collection = models.ForeignKey(WikiCollection, on_delete=models.CASCADE, related_name="page_collections")
    page = models.ForeignKey("db.Page", on_delete=models.CASCADE, related_name="wiki_page_collections")
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Wiki Page Collection"
        verbose_name_plural = "Wiki Page Collections"
        db_table = "ext_wiki_page_collections"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["page"],
                condition=Q(deleted_at__isnull=True),
                name="ext_wiki_page_collection_one_per_page",
            ),
        ]
        indexes = [models.Index(fields=["collection", "sort_order"], name="ext_wiki_pc_order_idx")]
