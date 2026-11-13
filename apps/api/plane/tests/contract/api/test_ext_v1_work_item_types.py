# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract: work item types, properties, options, values and feature flags on
/api/v1/, in the paths and shapes plane-sdk 0.3.1 uses."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, IssueType, Project, ProjectMember, Workspace
from plane.db.models.issue_type import ProjectIssueType
from plane.ext.models import IssueProperty, IssuePropertyOption, IssuePropertyValue, PropertyTypeChoices

from .sdk_contract import (  # noqa: F401 - fixtures are used by name
    ADMIN,
    GUEST,
    MEMBER,
    PROJECT_FEATURE,
    WORK_ITEM_PROPERTY,
    WORK_ITEM_PROPERTY_OPTION,
    WORK_ITEM_PROPERTY_VALUE,
    WORK_ITEM_TYPE,
    assert_shape,
    celery_eager,
    other_project,
    project,
    role_client,
    state,
    v1,
)


@pytest.fixture
def task_type(project):
    return IssueType.objects.get(workspace=project.workspace, system_key=IssueType.SystemKey.TASK)


@pytest.fixture
def custom_type(project):
    issue_type = IssueType.objects.create(workspace=project.workspace, name="Bug")
    ProjectIssueType.objects.create(project=project, issue_type=issue_type)
    return issue_type


@pytest.fixture
def issue(workspace, project, state, task_type, create_user):
    issue = Issue(name="Typed", workspace=workspace, project=project, state=state, type=task_type)
    issue.save(created_by_id=create_user.id)
    return issue


def make_property(issue_type, property_type, **extra):
    return IssueProperty.objects.create(
        workspace=issue_type.workspace,
        issue_type=issue_type,
        display_name=extra.pop("display_name", property_type),
        property_type=property_type,
        **extra,
    )


@pytest.mark.contract
@pytest.mark.django_db
class TestWorkItemTypes:
    def test_requires_an_api_key(self, workspace, project):
        response = APIClient().get(f"{v1(workspace, project)}/work-item-types/")
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_list_is_a_plain_array_of_sdk_types(self, api_key_client, workspace, project):
        response = api_key_client.get(f"{v1(workspace, project)}/work-item-types/")
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert {row["name"] for row in response.data} >= {"Task", "Epic"}
        for row in response.data:
            assert_shape(row, WORK_ITEM_TYPE)
            assert row["project_ids"] == [str(project.id)]
        epic = next(row for row in response.data if row["name"] == "Epic")
        assert epic["is_epic"] is True and epic["level"] == 1

    def test_crud(self, api_key_client, workspace, project):
        base = f"{v1(workspace, project)}/work-item-types/"
        created = api_key_client.post(
            base, {"name": "Bug", "description": "Defects", "external_source": "jira", "external_id": "B-1",
                   "is_epic": True, "level": 3}, format="json"
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        assert_shape(created.data, WORK_ITEM_TYPE)
        # Hierarchy is server-controlled: a custom type is a level-0 non-epic.
        assert created.data["is_epic"] is False and created.data["level"] == 0
        assert created.data["external_id"] == "B-1"
        assert ProjectIssueType.objects.filter(project=project, issue_type_id=created.data["id"]).exists()

        detail = f"{base}{created.data['id']}/"
        assert api_key_client.get(detail).data["name"] == "Bug"
        updated = api_key_client.patch(detail, {"name": "Defect", "is_active": False}, format="json")
        assert updated.status_code == status.HTTP_200_OK
        assert updated.data["name"] == "Defect" and updated.data["is_active"] is False
        assert api_key_client.delete(detail).status_code == status.HTTP_204_NO_CONTENT
        assert api_key_client.get(detail).status_code == status.HTTP_404_NOT_FOUND

    def test_system_types_cannot_be_removed_or_deactivated(self, api_key_client, workspace, project, task_type):
        detail = f"{v1(workspace, project)}/work-item-types/{task_type.id}/"
        assert api_key_client.delete(detail).status_code == status.HTTP_400_BAD_REQUEST
        assert api_key_client.patch(detail, {"is_active": False}, format="json").status_code == 400

    def test_a_type_in_use_cannot_be_deleted(self, api_key_client, workspace, project, state, custom_type):
        Issue.objects.create(name="Uses it", workspace=workspace, project=project, state=state, type=custom_type)
        response = api_key_client.delete(f"{v1(workspace, project)}/work-item-types/{custom_type.id}/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_writes_are_admin_only_and_reads_include_guests(self, workspace, project, custom_type):
        member, _ = role_client(workspace, project, MEMBER)
        guest, _ = role_client(workspace, project, GUEST)
        base = f"{v1(workspace, project)}/work-item-types/"
        assert member.post(base, {"name": "Nope"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert member.patch(f"{base}{custom_type.id}/", {"name": "x"}, format="json").status_code == 403
        assert guest.get(base).status_code == status.HTTP_200_OK
        assert guest.get(f"{base}{custom_type.id}/").status_code == status.HTTP_200_OK

    def test_a_type_of_another_project_is_not_found(self, api_key_client, workspace, project, custom_type, create_user):
        second = other_project(workspace, create_user)
        response = api_key_client.get(f"{v1(workspace, second)}/work-item-types/{custom_type.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_another_workspace_is_refused(self, workspace, project, create_user):
        outsider, _ = role_client(
            Workspace.objects.create(name="Elsewhere", slug="elsewhere", owner=create_user), None, ADMIN
        )
        assert outsider.get(f"{v1(workspace, project)}/work-item-types/").status_code == status.HTTP_403_FORBIDDEN

    def test_workspace_catalogue_answers_workspace_not_managed(self, api_key_client, workspace, project, task_type):
        imported = api_key_client.post(
            f"{v1(workspace, project)}/import-work-item-types/", {"work_item_types": [str(task_type.id)]},
            format="json",
        )
        assert imported.status_code == status.HTTP_400_BAD_REQUEST
        assert imported.data["code"] == "workspace_not_managed"

        listing = api_key_client.get(f"{v1(workspace)}/work-item-types/")
        assert listing.status_code == status.HTTP_400_BAD_REQUEST
        assert listing.data["code"] == "workspace_not_managed"
        assert "workspace work item types are not enabled" in listing.data["error"].lower()
        created = api_key_client.post(f"{v1(workspace)}/work-item-properties/", {"display_name": "x"}, format="json")
        assert created.data["code"] == "workspace_not_managed"
        # Probed as a fallback by plane-sdk clients, which read 404 as "nothing here".
        probe = api_key_client.get(f"{v1(workspace)}/work-item-types/{task_type.id}/properties/")
        assert probe.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
@pytest.mark.django_db
class TestWorkItemProperties:
    def test_create_text_property_under_a_type(self, api_key_client, workspace, project, task_type):
        response = api_key_client.post(
            f"{v1(workspace, project)}/work-item-types/{task_type.id}/work-item-properties/",
            {"display_name": "Notes", "property_type": "TEXT", "settings": {"display_format": "single-line"},
             "is_required": False, "external_id": "ignored"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert_shape(response.data, WORK_ITEM_PROPERTY)
        assert response.data["property_type"] == "TEXT" and response.data["relation_type"] is None
        assert response.data["name"] == "Notes"
        assert str(response.data["issue_type"]) == str(task_type.id)
        assert IssueProperty.objects.get(pk=response.data["id"]).property_type == PropertyTypeChoices.TEXT

    def test_option_property_with_options_and_option_crud(self, api_key_client, workspace, project, task_type):
        response = api_key_client.post(
            f"{v1(workspace, project)}/work-item-types/{task_type.id}/work-item-properties/",
            {"display_name": "Areas", "property_type": "OPTION", "is_multi": True,
             "options": [{"name": "API", "is_default": True}, {"name": "Web"}]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["property_type"] == "OPTION" and response.data["is_multi"] is True
        assert {option["name"] for option in response.data["options"]} == {"API", "Web"}
        prop = IssueProperty.objects.get(pk=response.data["id"])
        assert prop.property_type == PropertyTypeChoices.MULTI_SELECT

        options_url = f"{v1(workspace, project)}/work-item-properties/{prop.id}/options/"
        listing = api_key_client.get(options_url)
        assert listing.status_code == status.HTTP_200_OK and len(listing.data) == 2
        for option in listing.data:
            assert_shape(option, WORK_ITEM_PROPERTY_OPTION)

        created = api_key_client.post(options_url, {"name": "Mobile", "description": "ignored"}, format="json")
        assert created.status_code == status.HTTP_201_CREATED
        assert_shape(created.data, WORK_ITEM_PROPERTY_OPTION)
        detail = f"{options_url}{created.data['id']}/"
        assert api_key_client.get(detail).data["name"] == "Mobile"
        assert api_key_client.patch(detail, {"name": "iOS"}, format="json").data["name"] == "iOS"
        assert api_key_client.delete(detail).status_code == status.HTTP_204_NO_CONTENT
        assert not IssuePropertyOption.objects.filter(pk=created.data["id"]).exists()

    def test_user_relation_maps_to_member_and_other_types_are_refused(
        self, api_key_client, workspace, project, task_type
    ):
        base = f"{v1(workspace, project)}/work-item-types/{task_type.id}/work-item-properties/"
        member = api_key_client.post(
            base, {"display_name": "Reviewer", "property_type": "RELATION", "relation_type": "USER"}, format="json"
        )
        assert member.status_code == status.HTTP_201_CREATED, member.data
        assert member.data["property_type"] == "RELATION" and member.data["relation_type"] == "USER"
        for payload in (
            {"display_name": "Calc", "property_type": "FORMULA"},
            {"display_name": "Doc", "property_type": "RELATION", "relation_type": "RICH_TEXT"},
        ):
            refused = api_key_client.post(base, payload, format="json")
            assert refused.status_code == status.HTTP_400_BAD_REQUEST
            assert "not supported" in str(refused.data)

    def test_options_only_on_option_properties(self, api_key_client, workspace, project, task_type):
        response = api_key_client.post(
            f"{v1(workspace, project)}/work-item-types/{task_type.id}/work-item-properties/",
            {"display_name": "Bad", "property_type": "DECIMAL", "options": [{"name": "x"}]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not IssueProperty.objects.filter(display_name="Bad").exists()

    def test_project_flat_and_type_scoped_routes(self, api_key_client, workspace, project, task_type, custom_type):
        prop = make_property(task_type, PropertyTypeChoices.NUMBER, display_name="Points")
        make_property(custom_type, PropertyTypeChoices.BOOLEAN, display_name="Regression")
        base = v1(workspace, project)

        flat = api_key_client.get(f"{base}/work-item-properties/")
        assert flat.status_code == status.HTTP_200_OK
        assert {row["display_name"] for row in flat.data} == {"Points", "Regression"}
        scoped = api_key_client.get(f"{base}/work-item-types/{task_type.id}/work-item-properties/")
        assert [row["display_name"] for row in scoped.data] == ["Points"]
        assert scoped.data[0]["property_type"] == "DECIMAL"

        assert api_key_client.get(f"{base}/work-item-properties/{prop.id}/").status_code == 200
        wrong_type = api_key_client.get(f"{base}/work-item-types/{custom_type.id}/work-item-properties/{prop.id}/")
        assert wrong_type.status_code == status.HTTP_404_NOT_FOUND

        updated = api_key_client.patch(
            f"{base}/work-item-types/{task_type.id}/work-item-properties/{prop.id}/",
            {"display_name": "Story points", "property_type": "DECIMAL"},
            format="json",
        )
        assert updated.status_code == status.HTTP_200_OK and updated.data["display_name"] == "Story points"
        retyped = api_key_client.patch(f"{base}/work-item-properties/{prop.id}/", {"property_type": "TEXT"},
                                       format="json")
        assert retyped.status_code == status.HTTP_400_BAD_REQUEST

        typeless = api_key_client.post(
            f"{base}/work-item-properties/", {"display_name": "Loose", "property_type": "TEXT"}, format="json"
        )
        assert typeless.status_code == status.HTTP_400_BAD_REQUEST
        attach = api_key_client.post(
            f"{base}/work-item-types/{custom_type.id}/properties/", {"properties": [str(prop.id)]}, format="json"
        )
        assert attach.status_code == status.HTTP_400_BAD_REQUEST

        assert api_key_client.delete(f"{base}/work-item-properties/{prop.id}/").status_code == 204
        assert not IssueProperty.objects.filter(pk=prop.id).exists()

    def test_non_object_bodies_are_refused(self, api_key_client, workspace, project, task_type, issue):
        prop = make_property(task_type, PropertyTypeChoices.TEXT)
        base = v1(workspace, project)
        for body in ([], "x"):
            for method, url in (
                ("post", f"{base}/work-item-types/{task_type.id}/work-item-properties/"),
                ("patch", f"{base}/work-item-properties/{prop.id}/"),
                ("post", f"{base}/work-items/{issue.id}/work-item-properties/{prop.id}/values/"),
            ):
                response = getattr(api_key_client, method)(url, body, format="json")
                assert response.status_code == status.HTTP_400_BAD_REQUEST, (method, url, body)

    def test_writes_are_admin_only(self, workspace, project, task_type):
        member, _ = role_client(workspace, project, MEMBER)
        prop = make_property(task_type, PropertyTypeChoices.SELECT)
        base = v1(workspace, project)
        assert member.get(f"{base}/work-item-properties/{prop.id}/").status_code == status.HTTP_200_OK
        assert member.delete(f"{base}/work-item-properties/{prop.id}/").status_code == status.HTTP_403_FORBIDDEN
        assert member.post(f"{base}/work-item-properties/{prop.id}/options/", {"name": "x"},
                           format="json").status_code == 403

    def test_a_property_of_another_project_is_not_found(
        self, api_key_client, workspace, project, custom_type, create_user
    ):
        prop = make_property(custom_type, PropertyTypeChoices.TEXT)
        second = other_project(workspace, create_user)
        response = api_key_client.get(f"{v1(workspace, second)}/work-item-properties/{prop.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert api_key_client.get(f"{v1(workspace, second)}/work-item-properties/{prop.id}/options/").status_code == 404


@pytest.mark.contract
@pytest.mark.django_db
class TestWorkItemPropertyValues:
    def url(self, workspace, project, issue, prop):
        return f"{v1(workspace, project)}/work-items/{issue.id}/work-item-properties/{prop.id}/values/"

    def test_single_value_set_get_delete(self, api_key_client, workspace, project, issue, task_type):
        prop = make_property(task_type, PropertyTypeChoices.TEXT)
        url = self.url(workspace, project, issue, prop)
        assert api_key_client.get(url).status_code == status.HTTP_404_NOT_FOUND

        created = api_key_client.post(url, {"value": "hello", "external_id": "x"}, format="json")
        assert created.status_code == status.HTTP_200_OK, created.data
        assert_shape(created.data, WORK_ITEM_PROPERTY_VALUE)
        assert created.data["value"] == "hello" and created.data["value_type"] == "TEXT"
        assert str(created.data["issue_id"]) == str(issue.id)
        assert str(created.data["property_id"]) == str(prop.id)

        replaced = api_key_client.patch(url, {"value": "again"}, format="json")
        assert replaced.data["value"] == "again"
        assert IssuePropertyValue.objects.filter(issue=issue, property=prop).count() == 1
        assert api_key_client.get(url).data["value"] == "again"

        assert api_key_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert api_key_client.get(url).status_code == status.HTTP_404_NOT_FOUND

    def test_typed_values(self, api_key_client, workspace, project, issue, task_type):
        decimal = make_property(task_type, PropertyTypeChoices.NUMBER, display_name="Estimate")
        boolean = make_property(task_type, PropertyTypeChoices.BOOLEAN, display_name="Flag")
        date = make_property(task_type, PropertyTypeChoices.DATE, display_name="Due")

        response = api_key_client.post(self.url(workspace, project, issue, decimal), {"value": 2.5}, format="json")
        assert response.data["value"] == 2.5 and response.data["value_type"] == "DECIMAL"
        response = api_key_client.post(self.url(workspace, project, issue, boolean), {"value": False}, format="json")
        assert response.data["value"] is False
        response = api_key_client.post(self.url(workspace, project, issue, date), {"value": "2026-01-31"},
                                       format="json")
        assert response.data["value"].startswith("2026-01-31") and response.data["value_type"] == "DATETIME"
        refused = api_key_client.post(self.url(workspace, project, issue, decimal), {"value": "lots"}, format="json")
        assert refused.status_code == status.HTTP_400_BAD_REQUEST

    def test_multi_value_replaces_and_answers_a_list(self, api_key_client, workspace, project, issue, task_type):
        prop = make_property(task_type, PropertyTypeChoices.MULTI_SELECT, is_multi=True)
        first, second = (
            IssuePropertyOption.objects.create(workspace=workspace, property=prop, name=name) for name in ("a", "b")
        )
        url = self.url(workspace, project, issue, prop)
        response = api_key_client.post(url, {"value": [str(first.id), str(second.id)]}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert {row["value"] for row in response.data} == {str(first.id), str(second.id)}
        response = api_key_client.post(url, {"value": str(second.id)}, format="json")
        assert [row["value"] for row in response.data] == [str(second.id)]

        foreign = IssuePropertyOption.objects.create(
            workspace=workspace, property=make_property(task_type, PropertyTypeChoices.SELECT, display_name="Other"),
            name="c",
        )
        assert api_key_client.post(url, {"value": [str(foreign.id)]}, format="json").status_code == 400

    def test_rich_text_and_foreign_type_properties_are_refused(
        self, api_key_client, workspace, project, issue, task_type, custom_type
    ):
        text = make_property(task_type, PropertyTypeChoices.TEXT)
        rich = api_key_client.post(
            self.url(workspace, project, issue, text), {"value": {"description_html": "<p>x</p>"}}, format="json"
        )
        assert rich.status_code == status.HTTP_400_BAD_REQUEST
        foreign = make_property(custom_type, PropertyTypeChoices.TEXT)
        response = api_key_client.post(self.url(workspace, project, issue, foreign), {"value": "x"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_guests(self, workspace, project, issue, task_type):
        prop = make_property(task_type, PropertyTypeChoices.TEXT)
        IssuePropertyValue.objects.create(
            workspace=workspace, project=project, issue=issue, property=prop, value_text="secret"
        )
        guest, _ = role_client(workspace, project, GUEST)
        url = self.url(workspace, project, issue, prop)
        # A restricted guest cannot see a work item somebody else created.
        assert guest.get(url).status_code == status.HTTP_404_NOT_FOUND
        assert guest.post(url, {"value": "x"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        project.guest_view_all_features = True
        project.save(update_fields=["guest_view_all_features"])
        assert guest.get(url).data["value"] == "secret"

    def test_a_work_item_of_another_project_is_not_found(
        self, api_key_client, workspace, project, issue, task_type, create_user
    ):
        prop = make_property(task_type, PropertyTypeChoices.TEXT)
        second = other_project(workspace, create_user)
        response = api_key_client.post(self.url(workspace, second, issue, prop), {"value": "x"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
@pytest.mark.django_db
class TestFeatures:
    def test_project_features_read_and_toggle(self, api_key_client, workspace, project):
        url = f"{v1(workspace, project)}/features/"
        response = api_key_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert_shape(response.data, PROJECT_FEATURE)
        assert response.data["epics"] is True and response.data["work_item_types"] is True
        assert response.data["modules"] is False

        response = api_key_client.patch(url, {"modules": True, "time_tracking": True, "epics": True}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["modules"] is True and response.data["time_tracking"] is True
        project.refresh_from_db()
        assert project.module_view is True and project.is_time_tracking_enabled is True

        assert api_key_client.patch(url, {"epics": False}, format="json").status_code == 400
        assert api_key_client.patch(url, {"workflows": True}, format="json").status_code == 400

    def test_enabling_work_item_types_provisions_system_types(self, api_key_client, workspace, create_user):
        bare = Project.objects.create(name="Bare", identifier="BARE", workspace=workspace)
        ProjectMember.objects.create(project=bare, member=create_user, workspace=workspace, role=ADMIN)
        url = f"{v1(workspace, bare)}/features/"
        assert api_key_client.get(url).data["work_item_types"] is False
        response = api_key_client.patch(url, {"work_item_types": True}, format="json")
        assert response.data["work_item_types"] is True and response.data["epics"] is True

    def test_only_admins_toggle(self, workspace, project):
        member, _ = role_client(workspace, project, MEMBER)
        url = f"{v1(workspace, project)}/features/"
        assert member.get(url).status_code == status.HTTP_200_OK
        assert member.patch(url, {"modules": True}, format="json").status_code == status.HTTP_403_FORBIDDEN

    def test_workspace_features_report_project_owned_types(self, api_key_client, workspace):
        response = api_key_client.get(f"{v1(workspace)}/features/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["work_item_types"] is False
        assert response.data["states_owned_by_workspace"] is False
        assert response.data["wiki"] is True
