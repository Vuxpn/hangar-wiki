# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract: worklogs on /api/v1/ in the paths and shapes plane-sdk 0.3.1 uses."""

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, Workspace
from plane.ext.models import IssueWorkLog

from .sdk_contract import (  # noqa: F401 - fixtures are used by name
    ADMIN,
    GUEST,
    MEMBER,
    PROJECT_WORKLOG_SUMMARY,
    WORK_ITEM_WORK_LOG,
    assert_shape,
    celery_eager,
    other_project,
    project,
    role_client,
    state,
    v1,
)


@pytest.fixture
def tracked(project):
    project.is_time_tracking_enabled = True
    project.save(update_fields=["is_time_tracking_enabled"])
    return project


@pytest.fixture
def issue(workspace, tracked, state):
    return Issue.objects.create(name="Timed", workspace=workspace, project=tracked, state=state)


def worklogs_url(workspace, project, issue):
    return f"{v1(workspace, project)}/work-items/{issue.id}/worklogs/"


def log(issue, user, duration):
    return IssueWorkLog.objects.create(
        issue=issue, project=issue.project, workspace=issue.workspace, logged_by=user, duration=duration
    )


@pytest.mark.contract
@pytest.mark.django_db
class TestWorkLogs:
    def test_requires_an_api_key(self, workspace, tracked, issue):
        response = APIClient().get(worklogs_url(workspace, tracked, issue))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_crud_in_sdk_shape(self, api_key_client, workspace, tracked, issue, create_user):
        url = worklogs_url(workspace, tracked, issue)
        created = api_key_client.post(url, {"duration": 90, "description": "review", "created_by": "x"}, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.data
        assert_shape(created.data, WORK_ITEM_WORK_LOG)
        assert created.data["duration"] == 90
        assert str(created.data["logged_by"]) == str(create_user.id)
        assert str(created.data["project_id"]) == str(tracked.id)
        assert str(created.data["workspace_id"]) == str(workspace.id)

        listing = api_key_client.get(url)
        assert listing.status_code == status.HTTP_200_OK
        assert isinstance(listing.data, list) and len(listing.data) == 1

        detail = f"{url}{created.data['id']}/"
        updated = api_key_client.patch(detail, {"duration": 30}, format="json")
        assert updated.status_code == status.HTTP_200_OK and updated.data["duration"] == 30
        assert api_key_client.delete(detail).status_code == status.HTTP_204_NO_CONTENT
        assert not IssueWorkLog.objects.filter(pk=created.data["id"]).exists()

    def test_duration_bounds(self, api_key_client, workspace, tracked, issue):
        for bad in (0, 24 * 60 + 1):
            response = api_key_client.post(worklogs_url(workspace, tracked, issue), {"duration": bad}, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, bad

    def test_disabled_time_tracking_answers_402(self, api_key_client, workspace, tracked, issue, create_user):
        entry = log(issue, create_user, 10)
        tracked.is_time_tracking_enabled = False
        tracked.save(update_fields=["is_time_tracking_enabled"])
        url = worklogs_url(workspace, tracked, issue)
        responses = [
            api_key_client.get(url),
            api_key_client.post(url, {"duration": 5}, format="json"),
            api_key_client.patch(f"{url}{entry.id}/", {"duration": 5}, format="json"),
            api_key_client.delete(f"{url}{entry.id}/"),
            api_key_client.get(f"{v1(workspace, tracked)}/total-worklogs/"),
        ]
        for response in responses:
            assert response.status_code == 402
            assert response.data["error"] == (
                "Time tracking is not enabled for this project. Enable it in project settings."
            )

    def test_guests_never_see_time_entries(self, workspace, tracked, issue, create_user):
        log(issue, create_user, 10)
        guest, _ = role_client(workspace, tracked, GUEST)
        url = worklogs_url(workspace, tracked, issue)
        assert guest.get(url).status_code == status.HTTP_403_FORBIDDEN
        assert guest.post(url, {"duration": 5}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert guest.get(f"{v1(workspace, tracked)}/total-worklogs/").status_code == status.HTTP_403_FORBIDDEN

    def test_only_the_author_or_an_admin_changes_an_entry(self, api_key_client, workspace, tracked, issue):
        member, member_user = role_client(workspace, tracked, MEMBER)
        other, _ = role_client(workspace, tracked, MEMBER)
        entry = log(issue, member_user, 20)
        detail = f"{worklogs_url(workspace, tracked, issue)}{entry.id}/"
        assert other.patch(detail, {"duration": 1}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert other.delete(detail).status_code == status.HTTP_403_FORBIDDEN
        assert member.patch(detail, {"duration": 25}, format="json").status_code == status.HTTP_200_OK
        assert api_key_client.delete(detail).status_code == status.HTTP_204_NO_CONTENT

    def test_a_work_item_of_another_project_is_not_found(
        self, api_key_client, workspace, tracked, issue, create_user
    ):
        entry = log(issue, create_user, 10)
        second = other_project(workspace, create_user)
        second.is_time_tracking_enabled = True
        second.save(update_fields=["is_time_tracking_enabled"])
        url = worklogs_url(workspace, second, issue)
        assert api_key_client.get(url).status_code == status.HTTP_404_NOT_FOUND
        assert api_key_client.post(url, {"duration": 5}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert api_key_client.delete(f"{url}{entry.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert IssueWorkLog.objects.filter(pk=entry.id).exists()

    def test_entries_of_a_deleted_work_item_are_not_found(self, api_key_client, workspace, tracked, issue,
                                                         create_user):
        entry = log(issue, create_user, 10)
        Issue.all_objects.filter(pk=issue.id).update(deleted_at=timezone.now())
        detail = f"{worklogs_url(workspace, tracked, issue)}{entry.id}/"
        assert api_key_client.patch(detail, {"duration": 5}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert api_key_client.delete(detail).status_code == status.HTTP_404_NOT_FOUND

    def test_another_workspace_is_refused(self, workspace, tracked, issue, create_user):
        elsewhere = Workspace.objects.create(name="Elsewhere", slug="elsewhere-wl", owner=create_user)
        outsider, _ = role_client(elsewhere, None, ADMIN)
        assert outsider.get(worklogs_url(workspace, tracked, issue)).status_code == status.HTTP_403_FORBIDDEN

    def test_project_summary_totals_minutes_per_work_item(self, api_key_client, workspace, tracked, issue, state,
                                                          create_user):
        second_issue = Issue.objects.create(name="Other", workspace=workspace, project=tracked, state=state)
        log(issue, create_user, 30)
        log(issue, create_user, 45)
        log(second_issue, create_user, 10)
        response = api_key_client.get(f"{v1(workspace, tracked)}/total-worklogs/")
        assert response.status_code == status.HTTP_200_OK
        for row in response.data:
            assert_shape(row, PROJECT_WORKLOG_SUMMARY)
        assert {row["issue_id"]: row["duration"] for row in response.data} == {
            str(issue.id): 75,
            str(second_issue.id): 10,
        }
