# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""API-key endpoints under /api/v1/ shaped after plane-sdk, so its clients
(the Plane MCP server among them) reach Hangar's fork features unmodified."""

from django.urls import path

from plane.ext.api_v1.views.epics import EpicDetailAPIEndpoint, EpicListCreateAPIEndpoint, EpicWorkItemsAPIEndpoint
from plane.ext.api_v1.views.features import ProjectFeaturesAPIEndpoint, WorkspaceFeaturesAPIEndpoint
from plane.ext.api_v1.views.properties import (
    WorkItemPropertyDetailAPIEndpoint,
    WorkItemPropertyListCreateAPIEndpoint,
    WorkItemPropertyOptionDetailAPIEndpoint,
    WorkItemPropertyOptionListCreateAPIEndpoint,
    WorkItemPropertyValueAPIEndpoint,
    WorkItemTypePropertyLinkAPIEndpoint,
)
from plane.ext.api_v1.views.types import (
    ImportWorkItemTypesAPIEndpoint,
    WorkItemTypeDetailAPIEndpoint,
    WorkItemTypeListCreateAPIEndpoint,
    WorkspaceCatalogueAPIEndpoint,
)
from plane.ext.api_v1.views.worklogs import (
    ProjectWorkLogSummaryAPIEndpoint,
    WorkLogDetailAPIEndpoint,
    WorkLogListCreateAPIEndpoint,
)

WORKSPACE = "workspaces/<str:slug>"
PROJECT = f"{WORKSPACE}/projects/<uuid:project_id>"
TYPE = f"{PROJECT}/work-item-types/<uuid:type_id>"
PROPERTY = f"{PROJECT}/work-item-properties/<uuid:property_id>"
WORK_ITEM = f"{PROJECT}/work-items/<uuid:work_item_id>"

urlpatterns = [
    # Feature flags
    path(f"{WORKSPACE}/features/", WorkspaceFeaturesAPIEndpoint.as_view(), name="v1-workspace-features"),
    path(f"{PROJECT}/features/", ProjectFeaturesAPIEndpoint.as_view(), name="v1-project-features"),
    # Work item types
    path(f"{PROJECT}/work-item-types/", WorkItemTypeListCreateAPIEndpoint.as_view(), name="v1-work-item-types"),
    path(f"{TYPE}/", WorkItemTypeDetailAPIEndpoint.as_view(), name="v1-work-item-type"),
    path(
        f"{PROJECT}/import-work-item-types/",
        ImportWorkItemTypesAPIEndpoint.as_view(),
        name="v1-import-work-item-types",
    ),
    # Properties, type-scoped and project-flat
    path(
        f"{TYPE}/work-item-properties/",
        WorkItemPropertyListCreateAPIEndpoint.as_view(),
        name="v1-work-item-type-properties",
    ),
    path(
        f"{TYPE}/work-item-properties/<uuid:property_id>/",
        WorkItemPropertyDetailAPIEndpoint.as_view(),
        name="v1-work-item-type-property",
    ),
    path(f"{TYPE}/properties/", WorkItemTypePropertyLinkAPIEndpoint.as_view(), name="v1-work-item-type-links"),
    path(
        f"{TYPE}/properties/<uuid:property_id>/",
        WorkItemTypePropertyLinkAPIEndpoint.as_view(),
        name="v1-work-item-type-link",
    ),
    path(
        f"{PROJECT}/work-item-properties/",
        WorkItemPropertyListCreateAPIEndpoint.as_view(),
        name="v1-work-item-properties",
    ),
    path(f"{PROPERTY}/", WorkItemPropertyDetailAPIEndpoint.as_view(), name="v1-work-item-property"),
    path(
        f"{PROPERTY}/options/",
        WorkItemPropertyOptionListCreateAPIEndpoint.as_view(),
        name="v1-work-item-property-options",
    ),
    path(
        f"{PROPERTY}/options/<uuid:option_id>/",
        WorkItemPropertyOptionDetailAPIEndpoint.as_view(),
        name="v1-work-item-property-option",
    ),
    path(
        f"{WORK_ITEM}/work-item-properties/<uuid:property_id>/values/",
        WorkItemPropertyValueAPIEndpoint.as_view(),
        name="v1-work-item-property-values",
    ),
    # Workspace-level catalogue, which Hangar does not have
    path(f"{WORKSPACE}/work-item-types/", WorkspaceCatalogueAPIEndpoint.as_view(), name="v1-workspace-types"),
    path(
        f"{WORKSPACE}/work-item-types/<uuid:type_id>/",
        WorkspaceCatalogueAPIEndpoint.as_view(),
        name="v1-workspace-type",
    ),
    path(
        f"{WORKSPACE}/work-item-types/<uuid:type_id>/properties/",
        WorkspaceCatalogueAPIEndpoint.as_view(missing_on_read=True),
        name="v1-workspace-type-properties",
    ),
    path(
        f"{WORKSPACE}/work-item-types/<uuid:type_id>/properties/<uuid:property_id>/",
        WorkspaceCatalogueAPIEndpoint.as_view(),
        name="v1-workspace-type-property",
    ),
    path(
        f"{WORKSPACE}/work-item-properties/",
        WorkspaceCatalogueAPIEndpoint.as_view(),
        name="v1-workspace-properties",
    ),
    path(
        f"{WORKSPACE}/work-item-properties/<uuid:property_id>/",
        WorkspaceCatalogueAPIEndpoint.as_view(),
        name="v1-workspace-property",
    ),
    path(
        f"{WORKSPACE}/work-item-properties/<uuid:property_id>/options/",
        WorkspaceCatalogueAPIEndpoint.as_view(),
        name="v1-workspace-property-options",
    ),
    path(
        f"{WORKSPACE}/work-item-properties/<uuid:property_id>/options/<uuid:option_id>/",
        WorkspaceCatalogueAPIEndpoint.as_view(),
        name="v1-workspace-property-option",
    ),
    # Worklogs
    path(f"{WORK_ITEM}/worklogs/", WorkLogListCreateAPIEndpoint.as_view(), name="v1-work-item-worklogs"),
    path(f"{WORK_ITEM}/worklogs/<uuid:pk>/", WorkLogDetailAPIEndpoint.as_view(), name="v1-work-item-worklog"),
    path(f"{PROJECT}/total-worklogs/", ProjectWorkLogSummaryAPIEndpoint.as_view(), name="v1-project-worklog-totals"),
    # Epics
    path(f"{PROJECT}/epics/", EpicListCreateAPIEndpoint.as_view(), name="v1-epics"),
    path(f"{PROJECT}/epics/<uuid:pk>/", EpicDetailAPIEndpoint.as_view(), name="v1-epic"),
    path(f"{PROJECT}/epics/<uuid:pk>/issues/", EpicWorkItemsAPIEndpoint.as_view(), name="v1-epic-work-items"),
]
