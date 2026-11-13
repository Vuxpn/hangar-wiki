# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Epics for plane-sdk clients.

An Epic is a work item of the project's Epic type (docs/epics-as-work-items.md),
so these endpoints are the core work-item endpoints narrowed to Epics: the
plane-sdk field names are translated and the request is handed to the core
view, which keeps validation, hierarchy rules, activity and webhooks in one place.
"""

import json

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from plane.api.serializers import IssueSerializer
from plane.api.views.base import BaseAPIView
from plane.api.views.issue import (
    IssueDetailAPIEndpoint,
    IssueListCreateAPIEndpoint,
    guest_cannot_view_issue,
    is_restricted_guest,
)
from plane.app.permissions import ProjectEntityPermission
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, Project
from plane.utils.host import base_host
from plane.ext.views.epic import EPIC_IMMUTABLE_FIELDS, epic_queryset, project_epic_type

from plane.ext.api_v1.helpers import feature_not_enabled, replace_request_data

EPIC = "Epic"
MAX_EPIC_WORK_ITEMS_PER_REQUEST = 100

# plane-sdk field -> core work-item serializer field
RENAMED_FIELDS = {"assignee_ids": "assignees", "label_ids": "labels"}


def epic_type_for(slug, project_id):
    return project_epic_type(Project.objects.get(workspace__slug=slug, pk=project_id))


def epic_payload(data):
    """plane-sdk's epic fields, renamed for the core serializer.

    Type and parent are server-controlled, as on the app API's Epic endpoint.
    """
    payload = {key: value for key, value in data.items() if key not in EPIC_IMMUTABLE_FIELDS}
    for sdk_field, core_field in RENAMED_FIELDS.items():
        if sdk_field in payload:
            payload[core_field] = payload.pop(sdk_field)
    return payload


def visible_epic(request, slug, project_id, pk):
    epic = epic_queryset(slug, project_id).get(pk=pk)
    if guest_cannot_view_issue(request.user.id, epic, slug):
        raise Issue.DoesNotExist
    return epic


class EpicListCreateAPIEndpoint(IssueListCreateAPIEndpoint):
    def get(self, request, slug, project_id):
        if epic_type_for(slug, project_id) is None:
            return feature_not_enabled(EPIC)
        epics = self.get_queryset().filter(type__is_epic=True)
        if is_restricted_guest(request.user.id, project_id, slug):
            epics = epics.filter(created_by=request.user)
        return self.paginate(
            request=request,
            queryset=epics,
            on_results=lambda page: IssueSerializer(page, many=True, fields=self.fields, expand=self.expand).data,
        )

    def post(self, request, slug, project_id):
        epic_type = epic_type_for(slug, project_id)
        if epic_type is None:
            return feature_not_enabled(EPIC)
        replace_request_data(request, {**epic_payload(request.data), "type_id": str(epic_type.id)})
        return super().post(request, slug, project_id)


class EpicDetailAPIEndpoint(IssueDetailAPIEndpoint):
    # The core view's PUT is an upsert by external id, not an epic operation.
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get(self, request, slug, project_id, pk):
        if epic_type_for(slug, project_id) is None:
            return feature_not_enabled(EPIC)
        visible_epic(request, slug, project_id, pk)
        return super().get(request, slug, project_id, pk)

    def patch(self, request, slug, project_id, pk):
        if epic_type_for(slug, project_id) is None:
            return feature_not_enabled(EPIC)
        visible_epic(request, slug, project_id, pk)
        replace_request_data(request, epic_payload(request.data))
        return super().patch(request, slug, project_id, pk)

    def delete(self, request, slug, project_id, pk):
        if epic_type_for(slug, project_id) is None:
            return feature_not_enabled(EPIC)
        visible_epic(request, slug, project_id, pk)
        return super().delete(request, slug, project_id, pk)


class EpicWorkItemsAPIEndpoint(BaseAPIView):
    """The work items directly below an Epic."""

    permission_classes = [ProjectEntityPermission]

    def get(self, request, slug, project_id, pk):
        if epic_type_for(slug, project_id) is None:
            return feature_not_enabled(EPIC)
        epic = visible_epic(request, slug, project_id, pk)
        children = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, parent=epic).select_related(
            "type"
        )
        if is_restricted_guest(request.user.id, project_id, slug):
            children = children.filter(created_by=request.user)
        return self.paginate(
            request=request,
            queryset=children.order_by("-created_at"),
            on_results=lambda page: IssueSerializer(page, many=True, fields=self.fields, expand=self.expand).data,
        )

    @transaction.atomic
    def post(self, request, slug, project_id, pk):
        if epic_type_for(slug, project_id) is None:
            return feature_not_enabled(EPIC)
        id_list = serializers.ListField(
            child=serializers.UUIDField(), allow_empty=False, max_length=MAX_EPIC_WORK_ITEMS_PER_REQUEST
        )
        try:
            work_item_ids = id_list.run_validation(request.data.get("work_item_ids"))
        except serializers.ValidationError as exc:
            return Response({"work_item_ids": exc.detail}, status=status.HTTP_400_BAD_REQUEST)
        work_item_ids = list(dict.fromkeys(work_item_ids))

        # Serialize hierarchy changes per project, as the sub-work-item endpoint does.
        Project.objects.select_for_update().get(pk=project_id, workspace__slug=slug)
        epic = epic_queryset(slug, project_id).select_for_update(of=("self",)).get(pk=pk)
        if epic.id in work_item_ids:
            return Response(
                {"work_item_ids": "A work item cannot be its own parent"}, status=status.HTTP_400_BAD_REQUEST
            )
        children = list(
            Issue.objects.select_for_update(of=("self",))
            .select_related("type")
            .filter(id__in=work_item_ids, workspace__slug=slug, project_id=project_id)
        )
        if len(children) != len(work_item_ids):
            return Response(
                {"work_item_ids": "Every work item must exist in this project"}, status=status.HTTP_400_BAD_REQUEST
            )
        if any(child.type_id and child.type.is_epic for child in children):
            return Response(
                {"work_item_ids": "Epic work items cannot have a parent"}, status=status.HTTP_400_BAD_REQUEST
            )

        previous_parents = {child.id: child.parent_id for child in children}
        for child in children:
            child.parent = epic
        Issue.objects.bulk_update(children, ["parent"], batch_size=10)

        def dispatch_activities():
            for child_id, previous in previous_parents.items():
                issue_activity.delay(
                    type="issue.activity.updated",
                    requested_data=json.dumps({"parent": str(epic.id)}),
                    actor_id=str(request.user.id),
                    issue_id=str(child_id),
                    project_id=str(project_id),
                    current_instance=json.dumps({"parent": str(previous) if previous else None}),
                    epoch=int(timezone.now().timestamp()),
                    notification=True,
                    origin=base_host(request=request, is_app=True),
                )

        transaction.on_commit(dispatch_activities)
        return Response(IssueSerializer(children, many=True).data, status=status.HTTP_200_OK)
