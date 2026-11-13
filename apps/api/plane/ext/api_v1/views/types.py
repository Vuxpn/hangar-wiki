# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work item types for plane-sdk clients.

Hangar keeps types per project: there is no workspace catalogue to import from,
so the catalogue routes answer with Plane's `workspace_not_managed` refusal,
which plane-sdk clients read as "pass project_id".
"""

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.app.permissions import (
    ROLE,
    ProjectAdminPermission,
    ProjectLitePermission,
    WorkspaceUserPermission,
    allow_permission,
)
from plane.db.models import Project

from plane.ext.api_v1.serializers.types import WorkItemTypeAPISerializer
from plane.ext.views.issue_type import (
    create_custom_issue_type,
    issue_type_delete_error,
    issue_type_update_error,
    project_issue_types,
)

WORKSPACE_NOT_MANAGED = {
    "error": "Workspace work item types are not enabled in Hangar: types and their properties "
    "belong to projects. Pass project_id.",
    "code": "workspace_not_managed",
}


class WorkItemTypeListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectLitePermission]

    def get(self, request, slug, project_id):
        issue_types = project_issue_types(slug, project_id).order_by("level", "created_at")
        return Response(
            WorkItemTypeAPISerializer(issue_types, many=True, context={"project_id": project_id}).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        serializer = WorkItemTypeAPISerializer(data=request.data, context={"project_id": project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        issue_type = create_custom_issue_type(project, serializer)
        return Response(
            WorkItemTypeAPISerializer(issue_type, context={"project_id": project_id}).data,
            status=status.HTTP_201_CREATED,
        )


class WorkItemTypeDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectLitePermission]

    def get(self, request, slug, project_id, type_id):
        issue_type = project_issue_types(slug, project_id).get(pk=type_id)
        return Response(
            WorkItemTypeAPISerializer(issue_type, context={"project_id": project_id}).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, type_id):
        issue_type = project_issue_types(slug, project_id).get(pk=type_id)
        serializer = WorkItemTypeAPISerializer(
            issue_type, data=request.data, partial=True, context={"project_id": project_id}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        if error := issue_type_update_error(issue_type, serializer.validated_data):
            return Response(error, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, type_id):
        issue_type = project_issue_types(slug, project_id).get(pk=type_id)
        if error := issue_type_delete_error(issue_type):
            return Response(error, status=status.HTTP_400_BAD_REQUEST)
        issue_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ImportWorkItemTypesAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectAdminPermission]

    def post(self, request, slug, project_id):
        return Response(WORKSPACE_NOT_MANAGED, status=status.HTTP_400_BAD_REQUEST)


class WorkspaceCatalogueAPIEndpoint(BaseAPIView):
    """Workspace-level types and properties, which Hangar does not have.

    Reading the properties linked to a workspace type answers 404 rather than
    the refusal: plane-sdk clients probe it as a fallback and treat 404 as
    "nothing here", where a 400 would fail the whole listing.
    """

    permission_classes = [WorkspaceUserPermission]
    missing_on_read = False

    def get(self, request, *args, **kwargs):
        if self.missing_on_read:
            return Response({"error": WORKSPACE_NOT_MANAGED["error"]}, status=status.HTTP_404_NOT_FOUND)
        return Response(WORKSPACE_NOT_MANAGED, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, *args, **kwargs):
        return Response(WORKSPACE_NOT_MANAGED, status=status.HTTP_400_BAD_REQUEST)

    patch = post
    delete = post
