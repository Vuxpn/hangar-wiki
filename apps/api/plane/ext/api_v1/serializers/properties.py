# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Translation between Hangar custom properties and plane-sdk's property shapes.

Hangar keeps its own property vocabulary (text, number, date, boolean, select,
multi_select, member). plane-sdk speaks Plane's (TEXT, DECIMAL, DATETIME,
BOOLEAN, OPTION, RELATION/USER, ...). Requests are translated into Hangar's
payload and validated by the app serializers, so the rules live in one place.
"""

from rest_framework import serializers

from plane.ext.models import IssuePropertyValue, PropertyTypeChoices
from plane.ext.serializers.issue_property import IssuePropertyOptionSerializer, IssuePropertySerializer
from plane.ext.utils.property_validators import MULTI_VALUE_TYPES

RELATION_USER = "USER"

# Hangar type -> (plane-sdk property_type, relation_type)
SDK_PROPERTY_TYPES = {
    PropertyTypeChoices.TEXT: ("TEXT", None),
    PropertyTypeChoices.NUMBER: ("DECIMAL", None),
    PropertyTypeChoices.DATE: ("DATETIME", None),
    PropertyTypeChoices.BOOLEAN: ("BOOLEAN", None),
    PropertyTypeChoices.SELECT: ("OPTION", None),
    PropertyTypeChoices.MULTI_SELECT: ("OPTION", None),
    PropertyTypeChoices.MEMBER: ("RELATION", RELATION_USER),
}

SCALAR_HANGAR_TYPES = {
    "TEXT": PropertyTypeChoices.TEXT,
    "DECIMAL": PropertyTypeChoices.NUMBER,
    "DATETIME": PropertyTypeChoices.DATE,
    "BOOLEAN": PropertyTypeChoices.BOOLEAN,
}

SUPPORTED_SDK_TYPES = "TEXT, DECIMAL, DATETIME, BOOLEAN, OPTION and RELATION with relation_type USER"

# plane-sdk fields copied unchanged into Hangar's property payload.
PASSTHROUGH_PROPERTY_FIELDS = (
    "display_name",
    "description",
    "is_required",
    "is_active",
    "is_multi",
    "default_value",
    "settings",
    "logo_props",
    "sort_order",
)


def is_multi_valued(prop):
    return prop.property_type in MULTI_VALUE_TYPES and prop.is_multi


def hangar_property_type(property_type, relation_type, is_multi):
    """The Hangar type for a plane-sdk type, or raise ValidationError."""
    if property_type in SCALAR_HANGAR_TYPES:
        return SCALAR_HANGAR_TYPES[property_type]
    if property_type == "OPTION":
        return PropertyTypeChoices.MULTI_SELECT if is_multi else PropertyTypeChoices.SELECT
    if property_type == "RELATION" and relation_type == RELATION_USER:
        return PropertyTypeChoices.MEMBER
    raise serializers.ValidationError(
        {"property_type": f"{property_type} properties are not supported. Hangar supports {SUPPORTED_SDK_TYPES}."}
    )


def property_payload(data, instance=None):
    """Translate a plane-sdk property request into Hangar's payload."""
    payload = {key: data[key] for key in PASSTHROUGH_PROPERTY_FIELDS if key in data}
    if "property_type" in data:
        is_multi = data.get("is_multi", getattr(instance, "is_multi", False))
        payload["property_type"] = hangar_property_type(data["property_type"], data.get("relation_type"), is_multi)
        if payload["property_type"] == PropertyTypeChoices.MULTI_SELECT:
            payload["is_multi"] = True
    return payload


class WorkItemPropertyOptionAPISerializer(IssuePropertyOptionSerializer):
    """An option in plane-sdk's `WorkItemPropertyOption` shape."""

    class Meta(IssuePropertyOptionSerializer.Meta):
        fields = IssuePropertyOptionSerializer.Meta.fields + ["workspace", "created_by", "updated_by"]
        read_only_fields = IssuePropertyOptionSerializer.Meta.read_only_fields + [
            "workspace",
            "created_by",
            "updated_by",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update(
            project=self.context.get("project_id"),
            description=None,
            parent=None,
            external_source=None,
            external_id=None,
        )
        return data


class WorkItemPropertyAPISerializer(IssuePropertySerializer):
    """A property in plane-sdk's `WorkItemProperty` shape (output only)."""

    options = serializers.SerializerMethodField()

    class Meta(IssuePropertySerializer.Meta):
        fields = IssuePropertySerializer.Meta.fields + ["workspace", "created_by", "updated_by"]
        read_only_fields = IssuePropertySerializer.Meta.fields + ["workspace", "created_by", "updated_by"]

    def get_options(self, obj):
        return WorkItemPropertyOptionAPISerializer(obj.options.all(), many=True, context=self.context).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        property_type, relation_type = SDK_PROPERTY_TYPES[instance.property_type]
        data.update(
            name=instance.display_name,
            property_type=property_type,
            relation_type=relation_type,
            project=self.context.get("project_id"),
            validation_rules=None,
            external_source=None,
            external_id=None,
        )
        return data


class WorkItemPropertyValueAPISerializer(serializers.ModelSerializer):
    """One stored value in plane-sdk's `WorkItemPropertyValueDetail` shape."""

    property_id = serializers.UUIDField(read_only=True)
    issue_id = serializers.UUIDField(read_only=True)
    value = serializers.SerializerMethodField()
    value_type = serializers.SerializerMethodField()

    class Meta:
        model = IssuePropertyValue
        fields = ["id", "property_id", "issue_id", "value", "value_type", "created_at", "updated_at"]
        read_only_fields = fields

    def get_value(self, row):
        prop_type = row.property.property_type
        if prop_type == PropertyTypeChoices.NUMBER:
            return float(row.value_number) if row.value_number is not None else None
        if prop_type == PropertyTypeChoices.BOOLEAN:
            return row.value_boolean
        if prop_type == PropertyTypeChoices.DATE:
            return row.value_date.isoformat() if row.value_date else None
        if prop_type in (PropertyTypeChoices.SELECT, PropertyTypeChoices.MULTI_SELECT):
            return str(row.value_option_id) if row.value_option_id else None
        if prop_type == PropertyTypeChoices.MEMBER:
            return str(row.value_member_id) if row.value_member_id else None
        return row.value_text

    def get_value_type(self, row):
        return SDK_PROPERTY_TYPES[row.property.property_type][0]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update(external_id=None, external_source=None)
        return data
