# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract: Epics on /api/v1/ in the paths and shapes plane-sdk 0.3.1 uses.

An Epic is a work item of the project's Epic type; these endpoints only narrow
the work-item API to Epics."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, IssueAssignee, IssueType, Label, Workspace
from plane.db.models.issue_type import ProjectIssueType

from .sdk_contract import (  # noqa: F401 - fixtures are used by name
    ADMIN,
    EPIC,
    EPIC_ISSUE,
    GUEST,
    MEMBER,
    PAGINATED,
    assert_shape,
    celery_eager,
    other_project,
    project,
    role_client,
    state,
    v1,
)


@pytest.fixture
def epic_type(project):
    return IssueType.objects.get(workspace=project.workspace, system_key=IssueType.SystemKey.EPIC)


@pytest.fixture
def task_type(project):
    return IssueType.objects.get(workspace=project.workspace, system_key=IssueType.SystemKey.TASK)


def make_item(project, state, issue_type, name, creator):
    item = Issue(name=name, workspace=project.workspace, project=project, state=state, type=issue_type)
    item.save(created_by_id=creator.id)
    return item


@pytest.fixture
def epic(project, state, epic_type, create_user):
    return make_item(project, state, epic_type, "Launch", create_user)


@pytest.fixture
def task(project, state, task_type, create_user):
    return make_item(project, state, task_type, "Write docs", create_user)


def epics_url(workspace, project):
    return f"{v1(workspace, project)}/epics/"


@pytest.mark.contract
@pytest.mark.django_db
class TestEpics:
    def test_requires_an_api_key(self, workspace, project):
        response = APIClient().get(epics_url(workspace, project))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_list_is_paginated_and_holds_only_epics(self, api_key_client, workspace, project, epic, task):
        response = api_key_client.get(epics_url(workspace, project))
        assert response.status_code == status.HTTP_200_OK
        assert_shape(response.data, PAGINATED)
        assert [str(row["id"]) for row in response.data["results"]] == [str(epic.id)]
        assert response.data["total_count"] == 1
        assert_shape(response.data["results"][0], EPIC)

    def test_create_translates_sdk_fields_and_forces_the_epic_type(
        self, api_key_client, workspace, project, state, epic_type, task, create_user
    ):
        label = Label.objects.create(name="Q3", project=project, workspace=workspace)
        response = api_key_client.post(
            epics_url(workspace, project),
            {"name": "Billing", "state_id": str(state.id), "assignee_ids": [str(create_user.id)],
             "label_ids": [str(label.id)], "priority": "high", "parent_id": str(task.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert_shape(response.data, EPIC)
        created = Issue.objects.get(pk=response.data["id"])
        assert created.type_id == epic_type.id and created.parent_id is None
        assert created.priority == "high"
        assert IssueAssignee.objects.filter(issue=created, assignee=create_user).exists()
        assert response.data["labels"] == [str(label.id)]

    def test_retrieve_update_delete(self, api_key_client, workspace, project, epic, task):
        detail = f"{epics_url(workspace, project)}{epic.id}/"
        assert api_key_client.get(detail).data["name"] == "Launch"
        updated = api_key_client.patch(detail, {"name": "Go live", "type_id": None}, format="json")
        assert updated.status_code == status.HTTP_200_OK, updated.data
        epic.refresh_from_db()
        assert epic.name == "Go live" and epic.type.is_epic
        assert api_key_client.delete(detail).status_code == status.HTTP_204_NO_CONTENT
        assert not Issue.objects.filter(pk=epic.id).exists()

        # A plain work item is not reachable through the Epic routes.
        not_epic = f"{epics_url(workspace, project)}{task.id}/"
        assert api_key_client.get(not_epic).status_code == status.HTTP_404_NOT_FOUND
        assert api_key_client.patch(not_epic, {"name": "x"}, format="json").status_code == 404
        assert api_key_client.delete(not_epic).status_code == status.HTTP_404_NOT_FOUND
        assert Issue.objects.filter(pk=task.id).exists()

    def test_work_items_below_an_epic(self, api_key_client, workspace, project, state, epic, task, epic_type,
                                      create_user):
        url = f"{epics_url(workspace, project)}{epic.id}/issues/"
        added = api_key_client.post(url, {"work_item_ids": [str(task.id)]}, format="json")
        assert added.status_code == status.HTTP_200_OK, added.data
        assert isinstance(added.data, list)
        assert_shape(added.data[0], EPIC_ISSUE)
        task.refresh_from_db()
        assert task.parent_id == epic.id

        listing = api_key_client.get(url)
        assert listing.status_code == status.HTTP_200_OK
        assert_shape(listing.data, PAGINATED)
        assert [str(row["id"]) for row in listing.data["results"]] == [str(task.id)]

        other_epic = make_item(project, state, epic_type, "Other", create_user)
        refused = api_key_client.post(url, {"work_item_ids": [str(other_epic.id)]}, format="json")
        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert api_key_client.post(url, {"work_item_ids": [str(epic.id)]}, format="json").status_code == 400
        assert api_key_client.post(url, {"work_item_ids": []}, format="json").status_code == 400

    def test_work_items_of_another_project_are_refused(
        self, api_key_client, workspace, project, state, epic, create_user
    ):
        second = other_project(workspace, create_user)
        foreign = Issue.objects.create(name="Foreign", workspace=workspace, project=second)
        url = f"{epics_url(workspace, project)}{epic.id}/issues/"
        response = api_key_client.post(url, {"work_item_ids": [str(foreign.id)]}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        foreign.refresh_from_db()
        assert foreign.parent_id is None
        assert api_key_client.get(f"{epics_url(workspace, second)}{epic.id}/").status_code == 404

    def test_without_the_epic_type_the_feature_answers_402(self, api_key_client, workspace, project, epic):
        ProjectIssueType.objects.filter(project=project, issue_type__system_key=IssueType.SystemKey.EPIC).delete()
        responses = [
            api_key_client.get(epics_url(workspace, project)),
            api_key_client.post(epics_url(workspace, project), {"name": "x"}, format="json"),
            api_key_client.get(f"{epics_url(workspace, project)}{epic.id}/"),
            api_key_client.get(f"{epics_url(workspace, project)}{epic.id}/issues/"),
        ]
        for response in responses:
            assert response.status_code == 402
            assert "is not enabled for this project" in response.data["error"]

    def test_restricted_guests_see_only_their_own_epics(self, workspace, project, state, epic, epic_type):
        guest, guest_user = role_client(workspace, project, GUEST)
        own = make_item(project, state, epic_type, "Mine", guest_user)
        response = guest.get(epics_url(workspace, project))
        assert [str(row["id"]) for row in response.data["results"]] == [str(own.id)]
        assert guest.get(f"{epics_url(workspace, project)}{epic.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert guest.get(f"{epics_url(workspace, project)}{epic.id}/issues/").status_code == 404
        assert guest.post(epics_url(workspace, project), {"name": "x"}, format="json").status_code == 403

    def test_members_create_and_another_workspace_is_refused(self, workspace, project, state, create_user):
        member, _ = role_client(workspace, project, MEMBER)
        assert member.post(epics_url(workspace, project), {"name": "Ok"}, format="json").status_code == 201
        elsewhere = Workspace.objects.create(name="Elsewhere", slug="elsewhere-ep", owner=create_user)
        outsider, _ = role_client(elsewhere, None, ADMIN)
        assert outsider.get(epics_url(workspace, project)).status_code == status.HTTP_403_FORBIDDEN
