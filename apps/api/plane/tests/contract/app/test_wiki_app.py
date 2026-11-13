# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace wiki over the web app's session routes, and the core paths it hooks into."""

import uuid

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import FileAsset, Page, User, Workspace, WorkspaceMember
from plane.utils.file_asset_permissions import can_read_file_asset

SLUG = "wiki-ws"
WIKI = f"/api/workspaces/{SLUG}/wiki"


def make_user(workspace, role):
    user = User.objects.create(email=f"{uuid.uuid4().hex[:8]}@example.com", username=uuid.uuid4().hex)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.fixture
def ws(db):
    owner = User.objects.create(email="owner@example.com", username=uuid.uuid4().hex)
    workspace = Workspace.objects.create(name="Wiki", slug=SLUG, owner=owner)
    WorkspaceMember.objects.create(workspace=workspace, member=owner, role=20, is_active=True)
    client = APIClient()
    client.force_authenticate(user=owner)
    return workspace, owner, client


def new_page(client, **data):
    response = client.post(f"{WIKI}/pages/", {"name": "Page", **data}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.json()


@pytest.mark.contract
@pytest.mark.django_db
class TestWikiAppPages:
    def test_list_carries_the_fields_the_page_store_reads(self, ws):
        _, _, client = ws
        parent = new_page(client)
        new_page(client, parent_id=parent["id"])
        pages = client.get(f"{WIKI}/pages/").json()
        by_id = {p["id"]: p for p in pages}
        assert {"parent", "is_favorite", "label_ids", "project_ids", "sub_pages_count", "collection_id"} <= set(
            by_id[parent["id"]]
        )
        assert by_id[parent["id"]]["sub_pages_count"] == 1
        assert "description_html" not in by_id[parent["id"]]

    def test_description_round_trip_for_the_live_server(self, ws):
        _, _, client = ws
        page = new_page(client)
        url = f"{WIKI}/pages/{page['id']}/description/"
        patched = client.patch(url, {"description_html": "<p>saved</p>"}, format="json")
        assert patched.status_code == status.HTTP_200_OK
        assert "saved" in Page.objects.get(pk=page["id"]).description_html
        assert client.get(url).status_code == status.HTTP_200_OK

    def test_move_under_a_child_is_refused(self, ws):
        _, _, client = ws
        parent = new_page(client)
        child = new_page(client, parent_id=parent["id"])
        response = client.post(f"{WIKI}/pages/{parent['id']}/move/", {"parent_id": child["id"]}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_move_to_another_collection_takes_the_subtree(self, ws):
        _, _, client = ws
        parent = new_page(client)
        child = new_page(client, parent_id=parent["id"])
        target = client.post(f"{WIKI}/collections/", {"name": "Eng"}, format="json").json()
        moved = client.post(
            f"{WIKI}/pages/{parent['id']}/move/", {"collection_id": target["id"], "sort_order": 5}, format="json"
        )
        assert moved.status_code == status.HTTP_200_OK
        assert moved.json()["collection_id"] == target["id"]
        assert client.get(f"{WIKI}/pages/{child['id']}/").json()["collection_id"] == target["id"]

    def test_promote_a_child_to_the_top_level(self, ws):
        _, _, client = ws
        parent = new_page(client)
        child = new_page(client, parent_id=parent["id"])
        moved = client.post(
            f"{WIKI}/pages/{child['id']}/move/", {"collection_id": parent["collection_id"]}, format="json"
        )
        assert moved.json()["parent"] is None

    def test_duplicate_stays_beside_the_source(self, ws):
        _, _, client = ws
        parent = new_page(client)
        child = new_page(client, parent_id=parent["id"], name="Spec")
        copy = client.post(f"{WIKI}/pages/{child['id']}/duplicate/").json()
        assert copy["name"] == "Spec (Copy)" and copy["parent"] == parent["id"]

    def test_lock_is_owner_or_admin(self, ws):
        workspace, _, client = ws
        page = new_page(client)
        _, member = make_user(workspace, 15)
        assert member.post(f"{WIKI}/pages/{page['id']}/lock/").status_code == status.HTTP_403_FORBIDDEN
        assert client.post(f"{WIKI}/pages/{page['id']}/lock/").status_code == status.HTTP_204_NO_CONTENT
        # A locked page refuses edits from anyone.
        assert member.patch(f"{WIKI}/pages/{page['id']}/", {"name": "x"}, format="json").status_code == 400

    def test_versions_are_scoped_to_the_page(self, ws):
        _, _, client = ws
        page = new_page(client)
        assert client.get(f"{WIKI}/pages/{page['id']}/versions/").json() == []

    def test_project_page_routes_do_not_see_wiki_pages(self, ws):
        """Wiki pages carry no project link, so project lists and lookups skip them."""
        _, _, client = ws
        page = new_page(client)
        assert not Page.objects.get(pk=page["id"]).projects.exists()


@pytest.mark.contract
@pytest.mark.django_db
class TestWikiCoreHooks:
    def test_asset_read_follows_the_wiki_policy(self, ws):
        workspace, owner, client = ws
        private = client.post(f"{WIKI}/collections/", {"name": "HR", "access": 1}, format="json").json()
        page = Page.objects.get(pk=new_page(client, collection_id=private["id"])["id"])
        asset = FileAsset.objects.create(
            workspace=workspace,
            page=page,
            entity_type=FileAsset.EntityTypeContext.PAGE_DESCRIPTION,
            asset="x/y.png",
            attributes={},
        )
        member, _ = make_user(workspace, 15)
        assert can_read_file_asset(user_id=owner.id, asset=asset)
        assert not can_read_file_asset(user_id=member.id, asset=asset)

    def test_upload_to_a_public_wiki_page_is_allowed_for_members(self, ws):
        workspace, _, client = ws
        page = new_page(client)
        _, member = make_user(workspace, 15)
        payload = {
            "entity_type": FileAsset.EntityTypeContext.PAGE_DESCRIPTION,
            "entity_identifier": page["id"],
            "name": "diagram.png",
            "size": 1024,
            "type": "image/png",
        }
        allowed = member.post(f"/api/assets/v2/workspaces/{SLUG}/", payload, format="json")
        assert allowed.status_code in (200, 201), allowed.data

        private = client.post(f"{WIKI}/collections/", {"name": "HR", "access": 1}, format="json").json()
        hidden = new_page(client, collection_id=private["id"])
        denied = member.post(
            f"/api/assets/v2/workspaces/{SLUG}/", {**payload, "entity_identifier": hidden["id"]}, format="json"
        )
        assert denied.status_code >= 400

    def test_global_search_finds_visible_wiki_pages_only(self, ws):
        workspace, _, client = ws
        new_page(client, name="Onboarding guide")
        private = client.post(f"{WIKI}/collections/", {"name": "HR", "access": 1}, format="json").json()
        new_page(client, name="Onboarding salaries", collection_id=private["id"])
        _, member = make_user(workspace, 15)
        response = member.get(f"/api/workspaces/{SLUG}/search/", {"search": "Onboarding", "workspace_search": "true"})
        assert response.status_code == status.HTTP_200_OK
        names = [p["name"] for p in response.json()["results"]["page"]]
        assert names == ["Onboarding guide"]
