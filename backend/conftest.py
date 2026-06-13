import os

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User

def pytest_configure() -> None:
    os.environ["DJANGO_TEST"] = "1"


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin-test",
        password="test-pass-1234",
        role=Role.ADMIN,
    )


@pytest.fixture
def editor_user(db):
    return User.objects.create_user(
        username="editor-test",
        password="test-pass-1234",
        role=Role.EDITOR,
    )


@pytest.fixture
def viewer_user(db):
    return User.objects.create_user(
        username="viewer-test",
        password="test-pass-1234",
        role=Role.VIEWER,
    )


@pytest.fixture
def auth_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture(autouse=True)
def _force_admin_session_client(request, admin_user):
    if "client" not in request.fixturenames:
        return
    client = request.getfixturevalue("client")
    client.force_login(admin_user)
