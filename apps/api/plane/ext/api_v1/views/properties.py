# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Custom properties, their options and their values for plane-sdk clients.

A Hangar property belongs to exactly one work item type. The project-flat
routes therefore read every property of the project's types, but cannot create
one without a type, and a property cannot be attached to or detached from
another type.
"""

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.api.views.issue import guest_cannot_view_issue
from plane.app.permissions import ROLE, ProjectAdminPermission, ProjectLitePermission, allow_permission
from plane.db.models import Issue
from plane.ext.models import IssueProperty, IssuePropertyValue
from plane.ext.serializers.issue_property import IssuePropertyOptionSerializer, IssuePropertySerializer
from plane.ext.services.workshop_properties import sync_trainer_assignees
from plane.ext.utils.property_validators import validate_property_values
from plane.ext.views.issue_type import (
    OPTION_PROPERTY_TYPES,
    project_issue_types,
    property_delete_error,
    scoped_option,
    scoped_property,
    writable_issue_properties,
)

from plane.ext.api_v1.serializers.properties import (
    WorkItemPropertyAPISerializer,
    WorkItemPropertyOptionAPISerializer,
    WorkItemPropertyValueAPISerializer,
    is_multi_valued,
    property_payload,
)

PROPERTY_NEEDS_TYPE = {
    "error": "In Hangar a property belongs to exactly one work item type. Create it under "
    "work-item-types/<type_id>/work-item-properties/ instead.",
}

PROPERTY_CANNOT_DETACH = {
    "error": "In Hangar a property belongs to exactly one work item type and cannot be detached. "
    "Delete the property instead.",
}

NO_VALUE = {"error": "This property has no value on this work item."}


def project_properties(slug, project_id):
    return IssueProperty.objects.filter(
        workspace__slug=slug, issue_type__in=project_issue_types(slug, project_id)
    ).prefetch_related("options")


def get_property(slug, project_id, property_id, type_id=None):
    prop = scoped_property(slug, project_id, property_id)
    if type_id is not None and prop.issue_type_id != type_id:
        raise IssueProperty.DoesNotExist
    return prop


class WorkItemPropertyListCreateAPIEndpoint(BaseAPIView):
    """Properties of one type, or of the whole project when no type is named."""

    permission_classes = [ProjectLitePermission]

    def get(self, request, slug, project_id, type_id=None):
        properties = project_properties(slug, project_id)
        if type_id is not None:
            properties = properties.filter(issue_type=project_issue_types(slug, project_id).get(pk=type_id))
        return Response(
            WorkItemPropertyAPISerializer(properties, many=True, context={"project_id": project_id}).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id, type_id=None):
        if type_id is None:
            return Response(PROPERTY_NEEDS_TYPE, status=status.HTTP_400_BAD_REQUEST)
        issue_type = project_issue_types(slug, project_id).get(pk=type_id)

        serializer = IssuePropertySerializer(data=property_payload(request.data))
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        options = request.data.get("options") or []
        if options and serializer.validated_data["property_type"] not in OPTION_PROPERTY_TYPES:
            return Response(
                {"options": "Options are only valid for OPTION properties"}, status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            prop = serializer.save(issue_type=issue_type, workspace=issue_type.workspace)
            for option in options:
                option_serializer = IssuePropertyOptionSerializer(data=option)
                option_serializer.is_valid(raise_exception=True)
                option_serializer.save(property=prop, workspace=prop.workspace)
        return Response(
            WorkItemPropertyAPISerializer(prop, context={"project_id": project_id}).data,
            status=status.HTTP_201_CREATED,
        )


class WorkItemPropertyDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectLitePermission]

    def get(self, request, slug, project_id, property_id, type_id=None):
        prop = get_property(slug, project_id, property_id, type_id)
        return Response(
            WorkItemPropertyAPISerializer(prop, context={"project_id": project_id}).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, property_id, type_id=None):
        prop = get_property(slug, project_id, property_id, type_id)
        serializer = IssuePropertySerializer(prop, data=property_payload(request.data, prop), partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        prop = serializer.save()
        return Response(
            WorkItemPropertyAPISerializer(prop, context={"project_id": project_id}).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, property_id, type_id=None):
        prop = get_property(slug, project_id, property_id, type_id)
        if error := property_delete_error(prop):
            return Response(error, status=status.HTTP_400_BAD_REQUEST)
        prop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkItemTypePropertyLinkAPIEndpoint(BaseAPIView):
    """Attaching or detaching properties, which Hangar's model does not allow."""

    permission_classes = [ProjectAdminPermission]

    def post(self, request, slug, project_id, type_id, property_id=None):
        return Response(PROPERTY_NEEDS_TYPE, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, slug, project_id, type_id, property_id=None):
        return Response(PROPERTY_CANNOT_DETACH, status=status.HTTP_400_BAD_REQUEST)


class WorkItemPropertyOptionListCreateAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectLitePermission]

    def get(self, request, slug, project_id, property_id):
        prop = scoped_property(slug, project_id, property_id)
        return Response(
            WorkItemPropertyOptionAPISerializer(prop.options.all(), many=True, context={"project_id": project_id}).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id, property_id):
        prop = scoped_property(slug, project_id, property_id)
        if prop.property_type not in OPTION_PROPERTY_TYPES:
            return Response(
                {"error": "Options are only valid for OPTION properties"}, status=status.HTTP_400_BAD_REQUEST
            )
        serializer = WorkItemPropertyOptionAPISerializer(data=request.data, context={"project_id": project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save(property=prop, workspace=prop.workspace)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WorkItemPropertyOptionDetailAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectLitePermission]

    def get(self, request, slug, project_id, property_id, option_id):
        option = scoped_option(slug, project_id, property_id, option_id)
        return Response(
            WorkItemPropertyOptionAPISerializer(option, context={"project_id": project_id}).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, property_id, option_id):
        option = scoped_option(slug, project_id, property_id, option_id)
        serializer = WorkItemPropertyOptionAPISerializer(
            option, data=request.data, partial=True, context={"project_id": project_id}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, property_id, option_id):
        scoped_option(slug, project_id, property_id, option_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def raw_values(value):
    """plane-sdk sends a typed value; Hangar's validators take a list of strings."""
    if isinstance(value, dict):
        return None
    values = value if isinstance(value, list) else [value]
    if any(isinstance(item, (dict, list)) for item in values):
        return None
    return [str(item).lower() if isinstance(item, bool) else item for item in values]


class WorkItemPropertyValueAPIEndpoint(BaseAPIView):
    """The value(s) of one property on one work item.

    A single-value property reads and writes one value; a multi-value one a
    list, and a write replaces every existing value.
    """

    permission_classes = [ProjectLitePermission]

    def get_target(self, request, slug, project_id, work_item_id, property_id):
        issue = Issue.objects.get(workspace__slug=slug, project_id=project_id, pk=work_item_id)
        if guest_cannot_view_issue(request.user.id, issue, slug):
            raise Issue.DoesNotExist
        return issue, writable_issue_properties(slug, project_id, issue).get(pk=property_id)

    def respond(self, prop, rows, status_code=status.HTTP_200_OK):
        data = WorkItemPropertyValueAPISerializer(rows, many=True).data
        if is_multi_valued(prop):
            return Response(data, status=status_code)
        if not data:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(data[0], status=status_code)

    def get_rows(self, issue, prop):
        return IssuePropertyValue.objects.filter(issue=issue, property=prop).select_related("property")

    def get(self, request, slug, project_id, work_item_id, property_id):
        issue, prop = self.get_target(request, slug, project_id, work_item_id, property_id)
        rows = self.get_rows(issue, prop)
        if not rows:
            return Response(NO_VALUE, status=status.HTTP_404_NOT_FOUND)
        return self.respond(prop, rows)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, work_item_id, property_id):
        issue, prop = self.get_target(request, slug, project_id, work_item_id, property_id)
        if "value" not in request.data:
            return Response({"value": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
        values = raw_values(request.data["value"])
        if values is None:
            return Response(
                {"value": "Rich text and nested values are not supported by Hangar properties."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rows = validate_property_values(prop, values, project_id)

        with transaction.atomic():
            # Serialize writes to this work item's values, as the bundle endpoint does.
            Issue.objects.select_for_update().get(pk=issue.pk)
            self.get_rows(issue, prop).delete()
            IssuePropertyValue.objects.bulk_create(
                IssuePropertyValue(issue=issue, property=prop, project_id=project_id, workspace=issue.workspace, **row)
                for row in rows
            )
            sync_trainer_assignees(issue, actor=request.user)
        return self.respond(prop, self.get_rows(issue, prop))

    patch = post

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, work_item_id, property_id):
        issue, prop = self.get_target(request, slug, project_id, work_item_id, property_id)
        rows = self.get_rows(issue, prop)
        if not rows:
            return Response(NO_VALUE, status=status.HTTP_404_NOT_FOUND)
        if prop.is_required:
            return Response({"error": "This property is required"}, status=status.HTTP_400_BAD_REQUEST)
        rows.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
