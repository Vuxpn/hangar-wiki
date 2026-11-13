# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Wiki routes for the web app, mounted under /api/."""

from django.urls import path

from plane.ext.wiki import views

WIKI = "workspaces/<str:slug>/wiki"
PAGE = f"{WIKI}/pages/<uuid:page_id>"
COLLECTION = f"{WIKI}/collections/<uuid:collection_id>"

urlpatterns = [
    path(f"{WIKI}/collections/", views.AppCollectionsEndpoint.as_view(), name="wiki-collections"),
    path(f"{COLLECTION}/", views.AppCollectionDetailEndpoint.as_view(), name="wiki-collection-detail"),
    path(f"{COLLECTION}/members/", views.AppCollectionMembersEndpoint.as_view(), name="wiki-collection-members"),
    path(
        f"{COLLECTION}/members/<uuid:member_id>/",
        views.AppCollectionMemberDetailEndpoint.as_view(),
        name="wiki-collection-member-detail",
    ),
    path(f"{WIKI}/pages/", views.AppPagesEndpoint.as_view(), name="wiki-pages"),
    path(f"{PAGE}/", views.AppPageDetailEndpoint.as_view(), name="wiki-page-detail"),
    path(f"{PAGE}/description/", views.AppPageDescriptionEndpoint.as_view(), name="wiki-page-description"),
    path(f"{PAGE}/archive/", views.AppPageArchiveEndpoint.as_view(), name="wiki-page-archive"),
    path(f"{PAGE}/lock/", views.AppPageLockEndpoint.as_view(), name="wiki-page-lock"),
    path(f"{PAGE}/move/", views.AppPageMoveEndpoint.as_view(), name="wiki-page-move"),
    path(f"{PAGE}/duplicate/", views.AppPageDuplicateEndpoint.as_view(), name="wiki-page-duplicate"),
    path(f"{PAGE}/versions/", views.AppPageVersionsEndpoint.as_view(), name="wiki-page-versions"),
    path(
        f"{PAGE}/versions/<uuid:version_id>/",
        views.AppPageVersionsEndpoint.as_view(),
        name="wiki-page-version-detail",
    ),
]
