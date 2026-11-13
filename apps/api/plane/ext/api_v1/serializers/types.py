# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.ext.serializers.issue_type import IssueTypeSerializer


class WorkItemTypeAPISerializer(IssueTypeSerializer):
    """A work item type in plane-sdk's `WorkItemType` shape.

    Validation is the app serializer's; this adds the fields the SDK reads.
    `project_ids` names only the project in the URL: a type shared by several
    projects must not reveal projects the caller may not see.
    """

    level = serializers.IntegerField(read_only=True)
    project_ids = serializers.SerializerMethodField()

    def get_project_ids(self, obj):
        project_id = self.context.get("project_id")
        return [str(project_id)] if project_id else []

    class Meta(IssueTypeSerializer.Meta):
        fields = IssueTypeSerializer.Meta.fields + [
            "project_ids",
            "external_source",
            "external_id",
            "created_by",
            "updated_by",
        ]
        read_only_fields = IssueTypeSerializer.Meta.read_only_fields + ["created_by", "updated_by"]
