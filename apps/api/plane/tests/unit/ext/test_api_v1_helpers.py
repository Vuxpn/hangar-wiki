# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""replace_request_data writes DRF's private Request._full_data.

If a DRF upgrade stops reading request.data from that attribute, the /api/v1/
epic and feature endpoints would silently hand the core views the untranslated
plane-sdk payload. This pins the behaviour they rely on.
"""

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from plane.ext.api_v1.helpers import replace_request_data, require_mapping


def json_request(body):
    django_request = APIRequestFactory().post("/", body, format="json")
    return Request(django_request, parsers=[JSONParser()])


@pytest.mark.unit
def test_request_data_returns_the_replaced_payload_after_parsing():
    request = json_request({"assignee_ids": ["a"]})
    assert request.data == {"assignee_ids": ["a"]}
    replace_request_data(request, {"assignees": ["a"]})
    assert request.data == {"assignees": ["a"]}


@pytest.mark.unit
def test_request_data_returns_the_replaced_payload_before_parsing():
    request = json_request({"assignee_ids": ["a"]})
    replace_request_data(request, {"assignees": ["a"]})
    assert request.data == {"assignees": ["a"]}


@pytest.mark.unit
@pytest.mark.parametrize("body", [[], "x", 3, None])
def test_non_object_bodies_are_refused(body):
    with pytest.raises(ValidationError):
        require_mapping(body)
    with pytest.raises(ValidationError):
        replace_request_data(json_request({}), body)
