# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Wiki routes for API keys, mounted under /api/v1/.

Paths match the commercial edition's public API so the official SDK and MCP
server reach them unchanged.
"""

from django.urls import path

from plane.ext.wiki import views

WS = "workspaces/<str:slug>"
PAGE = f"{WS}/pages/<uuid:page_id>"
COLLECTION = f"{WS}/collections/<uuid:collection_id>"

urlpatterns = [
    path(f"{WS}/pages/", views.ApiPagesEndpoint.as_view(), name="api-wiki-pages"),
    path(f"{PAGE}/", views.ApiPageDetailEndpoint.as_view(), name="api-wiki-page-detail"),
    path(f"{PAGE}/archive/", views.ApiPageArchiveEndpoint.as_view(), name="api-wiki-page-archive"),
    path(f"{WS}/collections/", views.ApiCollectionsEndpoint.as_view(), name="api-wiki-collections"),
    path(f"{COLLECTION}/", views.ApiCollectionDetailEndpoint.as_view(), name="api-wiki-collection-detail"),
    path(f"{COLLECTION}/pages/", views.ApiCollectionPagesEndpoint.as_view(), name="api-wiki-collection-pages"),
    path(
        f"{COLLECTION}/pages-search/",
        views.ApiCollectionPagesSearchEndpoint.as_view(),
        name="api-wiki-collection-pages-search",
    ),
    path(
        f"{COLLECTION}/pages/<uuid:page_collection_id>/",
        views.ApiCollectionPageDetailEndpoint.as_view(),
        name="api-wiki-collection-page-detail",
    ),
    path(f"{COLLECTION}/members/", views.ApiCollectionMembersEndpoint.as_view(), name="api-wiki-collection-members"),
    path(
        f"{COLLECTION}/members/<uuid:member_id>/",
        views.ApiCollectionMemberDetailEndpoint.as_view(),
        name="api-wiki-collection-member-detail",
    ),
]
