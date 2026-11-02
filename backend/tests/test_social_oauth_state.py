from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from app.routers.social_accounts import (
    facebook_callback,
    facebook_login,
    instagram_login,
    _instagram_response_data,
    validate_frontend_origin,
    verify_oauth_state,
)


def test_facebook_callback_returns_to_origin_used_to_start_oauth(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "test-app-id")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("FACEBOOK_CONFIG_ID", "test-config-id")
    monkeypatch.setenv(
        "FACEBOOK_REDIRECT_URI",
        "https://api.example.test/social-accounts/facebook/callback",
    )
    monkeypatch.setenv("FRONTEND_URLS", "http://localhost:5173")

    login_response = facebook_login(
        current_user_id=7,
        frontend_origin="http://localhost:5173",
    )
    authorization_params = parse_qs(
        urlparse(login_response["authorization_url"]).query
    )
    state = authorization_params["state"][0]

    assert verify_oauth_state(state, "test-app-secret")[0] == 7
    assert verify_oauth_state(state, "test-app-secret")[2] == (
        "http://localhost:5173"
    )

    callback_response = facebook_callback(
        state=state,
        error="access_denied",
        db=None,
    )

    assert urlparse(callback_response.headers["location"]).netloc == (
        "localhost:5173"
    )


def test_frontend_origin_validation_rejects_unlisted_origin(monkeypatch):
    monkeypatch.setenv("FRONTEND_URLS", "https://socialpilot.example")

    with pytest.raises(HTTPException) as error:
        validate_frontend_origin("https://untrusted.example")

    assert error.value.status_code == 400


def test_instagram_login_requests_current_business_permissions(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_ID", "test-instagram-app-id")
    monkeypatch.setenv(
        "INSTAGRAM_REDIRECT_URI",
        "https://api.example.test/social-accounts/instagram/callback",
    )

    login_response = instagram_login(current_user_id=7)
    authorization_params = parse_qs(
        urlparse(login_response["authorization_url"]).query
    )

    assert authorization_params["scope"] == [
        "instagram_business_basic,instagram_business_content_publish,"
        "instagram_business_manage_insights"
    ]


def test_instagram_response_parser_accepts_current_meta_envelope():
    assert _instagram_response_data({
        "data": [{
            "access_token": "test-token",
            "user_id": "instagram-user-id",
        }],
    }) == {
        "access_token": "test-token",
        "user_id": "instagram-user-id",
    }
    assert _instagram_response_data({
        "data": [{
            "user_id": "instagram-user-id",
            "username": "test-account",
        }],
    }) == {
        "user_id": "instagram-user-id",
        "username": "test-account",
    }
