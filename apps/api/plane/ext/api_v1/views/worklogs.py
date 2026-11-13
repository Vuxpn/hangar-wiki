# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Worklogs for plane-sdk clients. Durations are in minutes.

The rules are the app API's: guests never see time entries, only the author
or an admin may change one, and nothing answers while time tracking is off.
"""

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Sum
from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.app.permissions import ROLE, ProjectLitePermission, allow_permission
from plane.db.models import Issue
from plane.ext.models import IssueWorkLog
from plane.ext.views.worklog import can_modify, record_worklog_activity, time_tracking_enabled

from plane.ext.api_v1.helpers import feature_not_enabled
from plane.ext.api_v1.serializers.worklogs import WorkLogAPISerializer

TIME_TRACKING = "Time tracking"


class WorkLogListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectLitePermission]

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, work_item_id):
        if not time_tracking_enabled(slug, project_id):
            return feature_not_enabled(TIME_TRACKING)
        Issue.objects.get(workspace__slug=slug, project_id=project_id, pk=work_item_id)
        worklogs = IssueWorkLog.objects.filter(workspace__slug=slug, project_id=project_id, issue_id=work_item_id)
        return Response(WorkLogAPISerializer(worklogs, many=True).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, work_item_id):
        if not time_tracking_enabled(slug, project_id):
            return feature_not_enabled(TIME_TRACKING)
        issue = Issue.objects.get(workspace__slug=slug, project_id=project_id, pk=work_item_id)
        serializer = WorkLogAPISerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        # logged_by is never client-supplied.
        worklog = serializer.save(issue=issue, project_id=project_id, workspace=issue.workspace, logged_by=request.user)
        record_worklog_activity(request, "created", work_item_id, project_id, worklog.duration)
        return Response(WorkLogAPISerializer(worklog).data, status=status.HTTP_201_CREATED)


class WorkLogDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectLitePermission]

    def get_worklog(self, slug, project_id, work_item_id, pk):
        return IssueWorkLog.objects.get(
            workspace__slug=slug, project_id=project_id, issue_id=work_item_id, issue__deleted_at__isnull=True, pk=pk
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id, work_item_id, pk):
        if not time_tracking_enabled(slug, project_id):
            return feature_not_enabled(TIME_TRACKING)
        worklog = self.get_worklog(slug, project_id, work_item_id, pk)
        if not can_modify(worklog, request.user, slug, project_id):
            return Response(
                {"error": "Only the author or a project admin can edit this entry"},
                status=status.HTTP_403_FORBIDDEN,
            )
        current_instance = json.dumps(WorkLogAPISerializer(worklog).data, cls=DjangoJSONEncoder)
        serializer = WorkLogAPISerializer(worklog, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        worklog = serializer.save()
        record_worklog_activity(request, "updated", work_item_id, project_id, worklog.duration, current_instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, work_item_id, pk):
        if not time_tracking_enabled(slug, project_id):
            return feature_not_enabled(TIME_TRACKING)
        worklog = self.get_worklog(slug, project_id, work_item_id, pk)
        if not can_modify(worklog, request.user, slug, project_id):
            return Response(
                {"error": "Only the author or a project admin can delete this entry"},
                status=status.HTTP_403_FORBIDDEN,
            )
        duration = worklog.duration
        worklog.delete()
        record_worklog_activity(request, "deleted", work_item_id, project_id, duration)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectWorkLogSummaryAPIEndpoint(BaseAPIView):
    """Total minutes logged per work item in a project."""

    permission_classes = [ProjectLitePermission]

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        if not time_tracking_enabled(slug, project_id):
            return feature_not_enabled(TIME_TRACKING)
        totals = (
            IssueWorkLog.objects.filter(workspace__slug=slug, project_id=project_id, issue__deleted_at__isnull=True)
            .values("issue_id")
            .annotate(duration=Sum("duration"))
            .order_by("issue_id")
        )
        return Response(
            [{"issue_id": str(row["issue_id"]), "duration": row["duration"]} for row in totals],
            status=status.HTTP_200_OK,
        )
