# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.ext.serializers.worklog import IssueWorkLogSerializer


class WorkLogAPISerializer(IssueWorkLogSerializer):
    """A worklog in plane-sdk's `WorkItemWorkLog` shape; duration is in minutes."""

    issue_id = serializers.UUIDField(read_only=True)
    project_id = serializers.UUIDField(read_only=True)
    workspace_id = serializers.UUIDField(read_only=True)

    class Meta(IssueWorkLogSerializer.Meta):
        fields = [
            "id",
            "duration",
            "description",
            "logged_by",
            "issue_id",
            "project_id",
            "workspace_id",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [field for field in fields if field not in ("duration", "description")]
