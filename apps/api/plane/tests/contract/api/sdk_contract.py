# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared fixtures and plane-sdk 0.3.1 response shapes for the /api/v1/ fork endpoints.

plane-sdk is not a dependency, so its pydantic models are restated as the keys
each response must carry. `required` mirrors the models' required fields;
`fields` the optional ones Hangar fills in.
"""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from plane.celery import app as celery_app
from plane.db.models import Project, ProjectMember, State, User, WorkspaceMember
from plane.db.models.api import APIToken
from plane.ext.services import ensure_project_system_types

ADMIN, MEMBER, GUEST = 20, 15, 5

WORK_ITEM_TYPE = {"name"}, {"id", "project_ids", "description", "logo_props", "is_epic", "is_default", "is_active",
                             "level", "external_source", "external_id", "workspace", "created_at", "updated_at"}
WORK_ITEM_PROPERTY = {"display_name", "property_type"}, {
    "id", "name", "relation_type", "description", "is_required", "default_value", "settings", "is_active",
    "is_multi", "issue_type", "options", "project", "workspace", "created_at", "updated_at",
}
WORK_ITEM_PROPERTY_OPTION = {"name"}, {"id", "sort_order", "is_active", "is_default", "property", "project",
                                       "workspace", "parent"}
WORK_ITEM_PROPERTY_VALUE = {"id", "property_id", "issue_id", "value"}, {"value_type", "created_at", "updated_at"}
WORK_ITEM_WORK_LOG = set(), {"id", "description", "duration", "created_by", "updated_by", "project_id",
                             "workspace_id", "logged_by", "created_at", "updated_at"}
PROJECT_WORKLOG_SUMMARY = {"issue_id", "duration"}, set()
EPIC = {"name", "project", "workspace"}, {"id", "state", "priority", "type", "assignees", "labels", "parent",
                                          "description_html", "sequence_id"}
EPIC_ISSUE = {"id", "name"}, {"type_id", "parent", "project", "workspace", "state"}
PROJECT_FEATURE = set(), {"epics", "modules", "cycles", "views", "pages", "intakes", "work_item_types",
                          "workflows", "parallel_cycles", "project_updates"}
PAGINATED = {"total_count", "next_cursor", "prev_cursor", "next_page_results", "prev_page_results", "count",
             "total_pages", "total_results", "results"}, set()


def assert_shape(data, shape):
    required, optional = shape
    missing = (required | optional) - set(data)
    assert not missing, f"response lacks plane-sdk fields {sorted(missing)}: {data!r}"
    for key in required:
        assert data[key] is not None, f"plane-sdk requires {key}: {data!r}"


@pytest.fixture(autouse=True)
def celery_eager():
    """Run activity and webhook tasks in-process; there is no broker under test."""
    original = celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates = original


@pytest.fixture
def project(db, workspace, create_user):
    """A project with its system types; the token holder behind api_key_client is admin."""
    project = Project.objects.create(
        name="SDK Project", identifier="SDK", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=ADMIN, is_active=True)
    ensure_project_system_types(project)
    return project


@pytest.fixture
def state(db, workspace, project):
    return State.objects.create(name="Todo", group="unstarted", project=project, workspace=workspace, default=True)


def role_client(workspace, project, role, workspace_role=None):
    """An API-key client for a new user holding `role` in the project."""
    uid = uuid4().hex[:8]
    user = User.objects.create(email=f"sdk-{uid}@hangar.test", username=f"sdk_{uid}")
    WorkspaceMember.objects.create(
        workspace=workspace, member=user, role=workspace_role or role, is_active=True
    )
    if project is not None:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role, is_active=True)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=APIToken.objects.create(user=user, label="sdk").token)
    return client, user


def other_project(workspace, user, identifier="OTH"):
    """A second project in the same workspace where `user` is admin."""
    project = Project.objects.create(name=f"Other {identifier}", identifier=identifier, workspace=workspace)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=ADMIN, is_active=True)
    ensure_project_system_types(project)
    return project


def v1(workspace, project=None):
    base = f"/api/v1/workspaces/{workspace.slug}"
    return f"{base}/projects/{project.id}" if project is not None else base
