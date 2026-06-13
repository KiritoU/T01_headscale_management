import pytest
from django.conf import settings

import config.settings as project_settings


def test_session_and_csrf_cookie_secure_follow_debug():
    expected_secure = not project_settings.DEBUG
    assert settings.SESSION_COOKIE_SECURE == expected_secure
    assert settings.CSRF_COOKIE_SECURE == expected_secure


def test_session_lifetime_and_rotation_settings():
    assert settings.SESSION_COOKIE_AGE == 8 * 60 * 60
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
    assert settings.SESSION_SAVE_EVERY_REQUEST is True


def test_login_throttle_rate():
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] == "5/min"
