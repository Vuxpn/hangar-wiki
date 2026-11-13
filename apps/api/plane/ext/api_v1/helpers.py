# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared plumbing for the plane-sdk compatible /api/v1/ endpoints."""

from collections.abc import Mapping

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

# Plane answers a feature its plan lacks with 402, and plane-sdk clients (the
# MCP server's @plan_gated) turn that status into a readable refusal.
HTTP_402_FEATURE_DISABLED = 402


def feature_not_enabled(feature):
    return Response(
        {"error": f"{feature} is not enabled for this project. Enable it in project settings."},
        status=HTTP_402_FEATURE_DISABLED,
    )


def require_mapping(data):
    """Refuse a body that is valid JSON but not an object, such as [] or "x"."""
    if not isinstance(data, Mapping):
        raise ValidationError({"error": "Expected a JSON object"})
    return data


def replace_request_data(request, data):
    """Hand a translated payload to a core view that reads request.data.

    Lets a compatibility endpoint rename plane-sdk fields and then delegate to
    the core view, so validation, activity and webhooks stay in one place.

    Relies on DRF's private ``Request._full_data`` (verified against
    djangorestframework 3.18.2); a unit test guards against drift.
    """
    if not isinstance(data, dict):
        raise ValidationError({"error": "Expected a JSON object"})
    request._full_data = data
