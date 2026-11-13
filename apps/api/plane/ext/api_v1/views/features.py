# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project and workspace feature flags in plane-sdk's shape.

Plane's flags map onto Hangar's project columns where Hangar has the feature.
Work item types and the Epic type are always available once a project's
system types are provisioned, so they can be switched on but not off.
"""

from rest_framework import serializers, status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.api.views.project import ProjectDetailAPIEndpoint
from plane.app.permissions import ProjectBasePermission, ProjectLitePermission, WorkspaceUserPermission
from plane.db.models import Project
from plane.db.models.issue_type import ProjectIssueType
from plane.ext.services import ensure_project_system_types
from plane.ext.views.epic import project_epic_type

from plane.ext.api_v1.helpers import replace_request_data

# plane-sdk flag -> Project column
PROJECT_FLAG_COLUMNS = {
    "modules": "module_view",
    "cycles": "cycle_view",
    "views": "issue_views_view",
    "pages": "page_view",
    "intakes": "intake_view",
    "time_tracking": "is_time_tracking_enabled",
}
SYSTEM_TYPE_FLAGS = ("work_item_types", "epics")
UNSUPPORTED_PROJECT_FLAGS = ("workflows", "parallel_cycles", "project_updates")

WORKSPACE_FLAGS = (
    "project_grouping",
    "initiatives",
    "teams",
    "customers",
    "wiki",
    "pi",
    "work_item_types",
    "releases",
    "states_owned_by_workspace",
)


class ProjectFeaturesSerializer(serializers.Serializer):
    def get_fields(self):
        flags = (*PROJECT_FLAG_COLUMNS, *SYSTEM_TYPE_FLAGS, *UNSUPPORTED_PROJECT_FLAGS)
        return {flag: serializers.BooleanField(required=False) for flag in flags}

    def validate(self, attrs):
        for flag in SYSTEM_TYPE_FLAGS:
            if attrs.get(flag) is False:
                raise serializers.ValidationError({flag: "Work item types and Epics cannot be disabled in Hangar"})
        for flag in UNSUPPORTED_PROJECT_FLAGS:
            if attrs.get(flag):
                raise serializers.ValidationError({flag: "This feature is not available in Hangar"})
        return attrs


def project_features(project):
    features = {flag: getattr(project, column) for flag, column in PROJECT_FLAG_COLUMNS.items()}
    features["epics"] = project_epic_type(project) is not None
    features["work_item_types"] = ProjectIssueType.objects.filter(project=project).exists()
    features.update({flag: False for flag in UNSUPPORTED_PROJECT_FLAGS})
    return features


class ProjectFeaturesAPIEndpoint(ProjectDetailAPIEndpoint):
    """Read any member; change as a project admin through the core project update."""

    http_method_names = ["get", "patch", "head", "options"]
    permission_classes = [ProjectBasePermission]

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [ProjectLitePermission()]
        return [ProjectBasePermission()]

    def get(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        return Response(project_features(project), status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        serializer = ProjectFeaturesSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        flags = serializer.validated_data

        columns = {column: flags[flag] for flag, column in PROJECT_FLAG_COLUMNS.items() if flag in flags}
        if columns:
            replace_request_data(request, columns)
            response = super().patch(request, slug, pk=project_id)
            if response.status_code != status.HTTP_200_OK:
                return response
        if any(flags.get(flag) for flag in SYSTEM_TYPE_FLAGS):
            ensure_project_system_types(project)

        project.refresh_from_db()
        return Response(project_features(project), status=status.HTTP_200_OK)


class WorkspaceFeaturesAPIEndpoint(BaseAPIView):
    """None of Plane's workspace-level features exist in Hangar."""

    permission_classes = [WorkspaceUserPermission]

    def get(self, request, slug):
        return Response({flag: False for flag in WORKSPACE_FLAGS}, status=status.HTTP_200_OK)
