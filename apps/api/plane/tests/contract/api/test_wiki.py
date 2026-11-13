# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace wiki over the API-key surface.

Response keys are checked against the fields the official plane-sdk models
(``Page``, ``Collection``, ``CollectionPage``, ``CollectionBranchPage``,
``PaginatedResponse``) read, so the SDK and MCP server keep parsing them.
"""

from unittest import mock
from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Page, User, WorkspaceMember
from plane.db.models.api import APIToken
from plane.ext.models import WikiCollection, WikiPageCollection

SDK_PAGE_KEYS = {
    "id",
    "name",
    "description_html",
    "created_at",
    "updated_at",
    "owned_by",
    "workspace",
    "projects",
    "access",
    "is_locked",
    "archived_at",
    "parent_id",
    "collection_id",
    "page_collection_id",
}
SDK_COLLECTION_KEYS = {
    "id",
    "name",
    "owned_by_id",
    "access",
    "current_user_access",
    "has_pages",
    "is_default",
    "is_global",
    "logo_props",
    "sort_order",
    "workspace",
}
SDK_PAGINATION_KEYS = {
    "total_count",
    "next_cursor",
    "prev_cursor",
    "next_page_results",
    "prev_page_results",
    "count",
    "total_pages",
    "total_results",
    "results",
}

BASE = "/api/v1/workspaces/test-workspace"


def make_member(workspace, role, email=None):
    user = User.objects.create(email=email or f"{uuid4().hex[:8]}@example.com", username=uuid4().hex, first_name="W")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    token = APIToken.objects.create(user=user, label="t", token=f"tok-{uuid4().hex}")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token.token)
    return user, client


@pytest.fixture(autouse=True)
def no_live_server():
    """No live server runs in the suite; tests that need one patch ``_live_post``."""
    with mock.patch("plane.ext.wiki.services._live_url", return_value=None):
        yield


@pytest.fixture
def member(db, workspace):
    return make_member(workspace, 15)


@pytest.fixture
def guest(db, workspace):
    return make_member(workspace, 5)


def create_page(client, **data):
    payload = {"name": "Page", "description_html": "<p>body</p>", **data}
    return client.post(f"{BASE}/pages/", payload, format="json")


@pytest.mark.contract
class TestWikiPages:
    @pytest.mark.django_db
    def test_requires_api_key(self, api_client, workspace):
        assert api_client.get(f"{BASE}/pages/").status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.django_db
    def test_create_files_into_default_collection(self, api_key_client, workspace):
        response = create_page(api_key_client, name="Handbook")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        body = response.json()
        assert SDK_PAGE_KEYS <= set(body)
        default = WikiCollection.objects.get(workspace=workspace, is_default=True)
        assert body["collection_id"] == str(default.id)
        assert body["page_collection_id"]
        assert body["projects"] == []
        page = Page.objects.get(pk=body["id"])
        assert page.is_global and not page.projects.exists()

    @pytest.mark.django_db
    def test_nested_page_takes_parent_collection(self, api_key_client, workspace):
        parent = create_page(api_key_client).json()
        child = create_page(api_key_client, parent_id=parent["id"]).json()
        assert child["parent_id"] == parent["id"]
        assert child["collection_id"] == parent["collection_id"]

    @pytest.mark.django_db
    def test_parent_and_collection_together_rejected(self, api_key_client, workspace):
        parent = create_page(api_key_client).json()
        response = create_page(api_key_client, parent_id=parent["id"], collection_id=parent["collection_id"])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_list_is_paginated_and_excludes_project_pages(self, api_key_client, workspace, create_user):
        create_page(api_key_client, name="Wiki one")
        Page.objects.create(workspace=workspace, name="Not wiki", owned_by=create_user, is_global=False)
        response = api_key_client.get(f"{BASE}/pages/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert SDK_PAGINATION_KEYS <= set(body)
        assert [p["name"] for p in body["results"]] == ["Wiki one"]

    @pytest.mark.django_db
    def test_update_writes_content_without_live_server(self, api_key_client, workspace):
        page = create_page(api_key_client).json()
        with mock.patch("plane.ext.wiki.services._live_url", return_value=None):
            response = api_key_client.put(
                f"{BASE}/pages/{page['id']}/", {"name": "Renamed", "description_html": "<p>new</p>"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, response.data
        stored = Page.objects.get(pk=page["id"])
        assert stored.name == "Renamed"
        assert "new" in stored.description_html
        assert stored.description_binary is None  # rebuilt from HTML when next opened

    @pytest.mark.django_db
    def test_update_goes_through_open_live_document(self, api_key_client, workspace):
        page = create_page(api_key_client, description_html="<p>old</p>").json()
        with mock.patch("plane.ext.wiki.services._live_post", return_value={"applied": True}) as live:
            response = api_key_client.put(f"{BASE}/pages/{page['id']}/", {"description_html": "<p>x</p>"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert live.call_args.args[0] == "documents/replace/"
        assert live.call_args.args[1]["document_name"] == page["id"]
        # The live server saves the body; the API must not write underneath it.
        assert "old" in Page.objects.get(pk=page["id"]).description_html

    @pytest.mark.django_db
    def test_unreachable_live_server_writes_nothing(self, api_key_client, workspace):
        import requests

        page = create_page(api_key_client, description_html="<p>old</p>").json()
        with mock.patch("plane.ext.wiki.services._live_post", side_effect=requests.ConnectionError("down")):
            response = api_key_client.put(f"{BASE}/pages/{page['id']}/", {"description_html": "<p>x</p>"}, format="json")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "old" in Page.objects.get(pk=page["id"]).description_html

    @pytest.mark.django_db
    def test_locked_page_refuses_edits(self, api_key_client, workspace):
        page = create_page(api_key_client, is_locked=True).json()
        response = api_key_client.put(f"{BASE}/pages/{page['id']}/", {"name": "x"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_archive_then_delete(self, api_key_client, workspace):
        page = create_page(api_key_client).json()
        url = f"{BASE}/pages/{page['id']}/"
        assert api_key_client.delete(url).status_code == status.HTTP_400_BAD_REQUEST
        assert api_key_client.post(url + "archive/").status_code == status.HTTP_204_NO_CONTENT
        assert api_key_client.get(url).json()["archived_at"]
        assert api_key_client.delete(url + "archive/").status_code == status.HTTP_204_NO_CONTENT
        assert api_key_client.get(url).json()["archived_at"] is None
        api_key_client.post(url + "archive/")
        assert api_key_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert api_key_client.get(url).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_private_page_is_owner_only(self, api_key_client, workspace, member):
        page = create_page(api_key_client, access=1).json()
        _, other = member
        assert other.get(f"{BASE}/pages/{page['id']}/").status_code == status.HTTP_404_NOT_FOUND
        assert page["id"] not in [p["id"] for p in other.get(f"{BASE}/pages/").json()["results"]]

    @pytest.mark.django_db
    def test_non_member_cannot_read(self, api_key_client, workspace, db):
        page = create_page(api_key_client).json()
        outsider = User.objects.create(email="out@example.com", username=uuid4().hex)
        token = APIToken.objects.create(user=outsider, label="t", token="tok-outsider")
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=token.token)
        assert client.get(f"{BASE}/pages/{page['id']}/").status_code == status.HTTP_404_NOT_FOUND
        assert client.get(f"{BASE}/pages/").status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.contract
class TestWikiCollections:
    @pytest.mark.django_db
    def test_list_includes_default_and_sdk_keys(self, api_key_client, workspace):
        response = api_key_client.get(f"{BASE}/collections/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert isinstance(body, list) and body[0]["is_default"] is True
        assert SDK_COLLECTION_KEYS <= set(body[0])
        assert body[0]["current_user_access"] == 2

    @pytest.mark.django_db
    def test_access_is_fixed_after_creation(self, api_key_client, workspace):
        created = api_key_client.post(f"{BASE}/collections/", {"name": "Eng", "access": 0}, format="json").json()
        url = f"{BASE}/collections/{created['id']}/"
        assert api_key_client.patch(url, {"access": 1}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        renamed = api_key_client.patch(url, {"name": "Engineering"}, format="json")
        assert renamed.status_code == status.HTTP_200_OK and renamed.json()["name"] == "Engineering"

    @pytest.mark.django_db
    def test_private_collection_hidden_until_membership(self, api_key_client, workspace, member):
        user, other = member
        private = api_key_client.post(f"{BASE}/collections/", {"name": "HR", "access": 1}, format="json").json()
        page = create_page(api_key_client, collection_id=private["id"]).json()
        assert other.get(f"{BASE}/collections/{private['id']}/").status_code == status.HTTP_404_NOT_FOUND
        assert other.get(f"{BASE}/pages/{page['id']}/").status_code == status.HTTP_404_NOT_FOUND
        # Read-only membership: visible, not editable.
        added = api_key_client.post(
            f"{BASE}/collections/{private['id']}/members/", {"member": str(user.id), "access": 0}, format="json"
        )
        assert added.status_code == status.HTTP_201_CREATED
        assert other.get(f"{BASE}/pages/{page['id']}/").status_code == status.HTTP_200_OK
        assert other.put(f"{BASE}/pages/{page['id']}/", {"name": "x"}, format="json").status_code == 403
        # Upgrade to edit.
        api_key_client.patch(
            f"{BASE}/collections/{private['id']}/members/{added.json()['id']}/", {"access": 2}, format="json"
        )
        assert other.put(f"{BASE}/pages/{page['id']}/", {"name": "x"}, format="json").status_code == 200

    @pytest.mark.django_db
    def test_guest_sees_nothing_without_membership(self, api_key_client, workspace, guest):
        page = create_page(api_key_client).json()
        _, client = guest
        assert client.get(f"{BASE}/pages/{page['id']}/").status_code == status.HTTP_404_NOT_FOUND
        assert client.get(f"{BASE}/collections/").json() == []
        assert create_page(client).status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_branch_listing_and_moving_between_collections(self, api_key_client, workspace):
        root = create_page(api_key_client, name="Root").json()
        child = create_page(api_key_client, name="Child", parent_id=root["id"]).json()
        default_id = root["collection_id"]
        branch = api_key_client.get(f"{BASE}/collections/{default_id}/pages/").json()
        assert SDK_PAGINATION_KEYS <= set(branch)
        assert [r["page"]["id"] for r in branch["results"]] == [root["id"]]
        assert {"page_collection_id", "collection_id", "parent_id", "sort_order", "page"} <= set(branch["results"][0])
        children = api_key_client.get(f"{BASE}/collections/{default_id}/pages/?parent_id={root['id']}").json()
        assert [r["page"]["id"] for r in children["results"]] == [child["id"]]

        target = api_key_client.post(f"{BASE}/collections/", {"name": "Target"}, format="json").json()
        moved = api_key_client.patch(
            f"{BASE}/collections/{default_id}/pages/{root['page_collection_id']}/",
            {"collection": target["id"]},
            format="json",
        )
        assert moved.status_code == status.HTTP_200_OK, moved.data
        assert moved.json()["collection"] == target["id"]
        # The subtree follows its root.
        assert api_key_client.get(f"{BASE}/pages/{child['id']}/").json()["collection_id"] == target["id"]

    @pytest.mark.django_db
    def test_add_and_unfile(self, api_key_client, workspace):
        page = create_page(api_key_client).json()
        target = api_key_client.post(f"{BASE}/collections/", {"name": "T"}, format="json").json()
        search = api_key_client.get(f"{BASE}/collections/{target['id']}/pages-search/?search=Pa").json()
        assert page["id"] in [p["id"] for p in search]
        added = api_key_client.post(
            f"{BASE}/collections/{target['id']}/pages/", {"page_ids": [page["id"]]}, format="json"
        )
        assert added.status_code == status.HTTP_201_CREATED
        row = added.json()[0]
        assert {"id", "collection", "page", "sort_order"} <= set(row)
        removed = api_key_client.delete(f"{BASE}/collections/{target['id']}/pages/{row['id']}/")
        assert removed.status_code == status.HTTP_204_NO_CONTENT
        assert api_key_client.get(f"{BASE}/pages/{page['id']}/").json()["collection_id"] is None

    @pytest.mark.django_db
    def test_deleting_private_collection_keeps_pages_private(self, api_key_client, workspace, member):
        user, other = member
        private = api_key_client.post(f"{BASE}/collections/", {"name": "Secret", "access": 1}, format="json").json()
        page = create_page(api_key_client, collection_id=private["id"]).json()
        response = api_key_client.delete(f"{BASE}/collections/{private['id']}/?archive_pages=false")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        stored = Page.objects.get(pk=page["id"])
        assert stored.access == Page.PRIVATE_ACCESS and stored.archived_at is not None
        assert other.get(f"{BASE}/pages/{page['id']}/").status_code == status.HTTP_404_NOT_FOUND
        assert WikiPageCollection.objects.get(page=stored).collection.is_default

    @pytest.mark.django_db
    def test_default_collection_cannot_be_deleted(self, api_key_client, workspace):
        default = api_key_client.get(f"{BASE}/collections/").json()[0]
        assert api_key_client.delete(f"{BASE}/collections/{default['id']}/").status_code == 400

    @pytest.mark.django_db
    def test_member_cannot_manage_others_collection(self, api_key_client, workspace, member):
        _, other = member
        created = api_key_client.post(f"{BASE}/collections/", {"name": "Mine"}, format="json").json()
        url = f"{BASE}/collections/{created['id']}/"
        assert other.patch(url, {"name": "Theirs"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert other.delete(url).status_code == status.HTTP_403_FORBIDDEN
        # ...but may write pages in a public collection.
        assert create_page(other, collection_id=created["id"]).status_code == status.HTTP_201_CREATED


@pytest.mark.contract
class TestWikiReviewFixes:
    @pytest.mark.django_db
    def test_editor_of_private_collection_cannot_publish_its_pages(self, api_key_client, workspace, member):
        user, other = member
        private = api_key_client.post(f"{BASE}/collections/", {"name": "HR", "access": 1}, format="json").json()
        public = api_key_client.post(f"{BASE}/collections/", {"name": "All"}, format="json").json()
        page = create_page(api_key_client, collection_id=private["id"]).json()
        api_key_client.post(
            f"{BASE}/collections/{private['id']}/members/", {"member": str(user.id), "access": 2}, format="json"
        )
        row_url = f"{BASE}/collections/{private['id']}/pages/{page['page_collection_id']}/"
        assert other.delete(row_url).status_code == status.HTTP_403_FORBIDDEN
        assert other.patch(row_url, {"collection": public["id"]}, format="json").status_code == 403
        added = other.post(f"{BASE}/collections/{public['id']}/pages/", {"page_ids": [page["id"]]}, format="json")
        assert added.status_code == status.HTTP_403_FORBIDDEN
        # The collection's owner may.
        assert api_key_client.patch(row_url, {"collection": public["id"]}, format="json").status_code == 200

    @pytest.mark.django_db
    def test_deleting_a_page_keeps_its_children(self, api_key_client, workspace):
        parent = create_page(api_key_client).json()
        child = create_page(api_key_client, parent_id=parent["id"]).json()
        api_key_client.post(f"{BASE}/pages/{parent['id']}/archive/")
        assert api_key_client.delete(f"{BASE}/pages/{parent['id']}/").status_code == status.HTTP_204_NO_CONTENT
        kept = Page.objects.get(pk=child["id"])
        assert kept.parent_id is None and kept.deleted_at is None

    @pytest.mark.django_db
    def test_renaming_without_live_server_drops_the_stale_title(self, api_key_client, workspace):
        page = create_page(api_key_client).json()
        Page.objects.filter(pk=page["id"]).update(description_binary=b"old-state")
        api_key_client.put(f"{BASE}/pages/{page['id']}/", {"name": "New title"}, format="json")
        stored = Page.objects.get(pk=page["id"])
        assert stored.name == "New title" and stored.description_binary is None

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "payload",
        [{"name": 5, "description_html": "<p></p>"}, {"name": "x", "description_html": "<p></p>", "collection_id": "nope"}],
    )
    def test_malformed_create_is_a_400(self, api_key_client, workspace, payload):
        assert api_key_client.post(f"{BASE}/pages/", payload, format="json").status_code == 400

    @pytest.mark.django_db
    def test_malformed_update_changes_nothing(self, api_key_client, workspace):
        page = create_page(api_key_client).json()
        response = api_key_client.put(
            f"{BASE}/pages/{page['id']}/", {"archived_at": "2026-01-01", "name": ""}, format="json"
        )
        assert response.status_code == 400
        assert Page.objects.get(pk=page["id"]).archived_at is None
