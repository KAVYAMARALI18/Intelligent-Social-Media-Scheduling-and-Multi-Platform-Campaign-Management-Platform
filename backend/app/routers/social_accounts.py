# backend/app/routers/social_accounts.py

import os
import base64
import hashlib
import hmac
import secrets
import requests

from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.database.postgres import get_db
from app.models.social_account import SocialAccount
from app.core.security import get_current_user


load_dotenv()

router = APIRouter(
    prefix="/social-accounts",
    tags=["Social Accounts"]
)


# ============================================================
# COMMON
# ============================================================

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:5173"
)


# ============================================================
# LINKEDIN OAUTH
# ============================================================

@router.get("/linkedin/login")
def linkedin_login(
    current_user_id: int = Depends(get_current_user)
):
    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI")

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="LINKEDIN_CLIENT_ID is not configured"
        )

    if not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="LINKEDIN_REDIRECT_URI is not configured"
        )

    random_state = secrets.token_urlsafe(32)

    state = f"{current_user_id}:{random_state}"

    scopes = "openid profile email w_member_social"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scopes,
    }

    authorization_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        + urlencode(params)
    )

    return {
        "authorization_url": authorization_url
    }


@router.get("/linkedin/callback")
def linkedin_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db)
):

    if error:
        message = error_description or error

        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"linkedin=error&message={message}"
            )
        )

    if not code or not state:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"linkedin=error&message=Invalid callback"
            )
        )

    try:
        user_id_text, _ = state.split(":", 1)
        user_id = int(user_id_text)
    except (ValueError, AttributeError):
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"linkedin=error&message=Invalid state"
            )
        )

    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
    redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI")

    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="LinkedIn OAuth configuration is incomplete"
        )

    # --------------------------------------------------------
    # Exchange authorization code for access token
    # --------------------------------------------------------

    token_response = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30
    )

    if token_response.status_code != 200:
        print(
            "LinkedIn token exchange failed:",
            token_response.status_code
        )

        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"linkedin=error&message=Token exchange failed"
            )
        )

    token_data = token_response.json()

    access_token = token_data.get("access_token")

    if not access_token:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"linkedin=error&message=Access token missing"
            )
        )

    # --------------------------------------------------------
    # Get LinkedIn user information
    # --------------------------------------------------------

    user_response = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={
            "Authorization": f"Bearer {access_token}"
        },
        timeout=30
    )

    if user_response.status_code != 200:
        print(
            "LinkedIn user info failed:",
            user_response.status_code
        )

        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"linkedin=error&message=Unable to get LinkedIn profile"
            )
        )

    linkedin_user = user_response.json()

    linkedin_id = linkedin_user.get("sub")
    name = linkedin_user.get("name")
    email = linkedin_user.get("email")

    username = name or email or linkedin_id

    # --------------------------------------------------------
    # Save / update account
    # --------------------------------------------------------

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == "linkedin"
        )
        .first()
    )

    if account:
        account.username = username
        account.access_token = access_token
        account.channel_id = linkedin_id
    else:
        account = SocialAccount(
            user_id=user_id,
            platform="linkedin",
            username=username,
            access_token=access_token,
            channel_id=linkedin_id
        )

        db.add(account)

    db.commit()
    db.refresh(account)

    return RedirectResponse(
        url=(
            f"{FRONTEND_URL}/social-accounts?"
            f"linkedin=connected&account_id={account.id}"
        )
    )


# ============================================================
# YOUTUBE OAUTH
# ============================================================

@router.get("/youtube/login")
def youtube_login(
    current_user_id: int = Depends(get_current_user)
):

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI")

    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="Google/YouTube OAuth configuration is incomplete"
        )

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ]
    )

    flow.redirect_uri = redirect_uri

    random_state = secrets.token_urlsafe(32)

    state = f"{current_user_id}:{random_state}"

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state
    )

    return {
        "authorization_url": authorization_url
    }


@router.get("/youtube/callback")
def youtube_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db)
):

    if error:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"youtube=error&message={error}"
            )
        )

    if not code or not state:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"youtube=error&message=Invalid callback"
            )
        )

    try:
        user_id_text, _ = state.split(":", 1)
        user_id = int(user_id_text)
    except (ValueError, AttributeError):
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"youtube=error&message=Invalid state"
            )
        )

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI")

    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth configuration is incomplete"
        )

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ]
    )

    flow.redirect_uri = redirect_uri

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        print("YouTube token exchange failed:", str(e))

        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"youtube=error&message=Token exchange failed"
            )
        )

    credentials = flow.credentials

    access_token = credentials.token
    refresh_token = credentials.refresh_token

    if not access_token:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"youtube=error&message=Access token missing"
            )
        )

    # --------------------------------------------------------
    # Get YouTube channel information
    # --------------------------------------------------------

    try:
        youtube = build(
            "youtube",
            "v3",
            credentials=credentials
        )

        response = youtube.channels().list(
            part="snippet",
            mine=True
        ).execute()

    except Exception as e:
        print("YouTube channel lookup failed:", str(e))

        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"youtube=error&message=Unable to get YouTube channel"
            )
        )

    items = response.get("items", [])

    if not items:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"youtube=error&message=No YouTube channel found"
            )
        )

    channel = items[0]

    channel_id = channel.get("id")

    channel_title = (
        channel.get("snippet", {})
        .get("title")
    )

    # --------------------------------------------------------
    # Save / update account
    # --------------------------------------------------------

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == "youtube"
        )
        .first()
    )

    if account:
        account.username = channel_title
        account.access_token = access_token
        account.refresh_token = refresh_token or account.refresh_token
        account.channel_id = channel_id

    else:
        account = SocialAccount(
            user_id=user_id,
            platform="youtube",
            username=channel_title,
            access_token=access_token,
            refresh_token=refresh_token,
            channel_id=channel_id
        )

        db.add(account)

    db.commit()
    db.refresh(account)

    return RedirectResponse(
        url=(
            f"{FRONTEND_URL}/social-accounts?"
            f"youtube=connected&account_id={account.id}"
        )
    )


# ============================================================
# INSTAGRAM
# ============================================================

def _instagram_response_data(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict):
        return data
    return payload


@router.get("/instagram/login")
def instagram_login(
    current_user_id: int = Depends(get_current_user)
):

    app_id = os.getenv("INSTAGRAM_APP_ID")
    redirect_uri = os.getenv("INSTAGRAM_REDIRECT_URI")

    if not app_id:
        raise HTTPException(
            status_code=500,
            detail="INSTAGRAM_APP_ID is not configured"
        )

    if not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="INSTAGRAM_REDIRECT_URI is not configured"
        )

    random_state = secrets.token_urlsafe(32)

    state = f"{current_user_id}:{random_state}"

    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": (
            "instagram_business_basic,"
            "instagram_business_content_publish,"
            "instagram_business_manage_insights"
        ),
        "state": state,
    }

    authorization_url = (
        "https://www.instagram.com/oauth/authorize?"
        + urlencode(params)
    )

    return {
        "authorization_url": authorization_url
    }


@router.get("/instagram/callback")
def instagram_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db)
):

    if error:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"instagram=error&message={error}"
            )
        )

    if not code or not state:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"instagram=error&message=Invalid callback"
            )
        )

    try:
        user_id_text, _ = state.split(":", 1)
        user_id = int(user_id_text)
    except (ValueError, AttributeError):
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"instagram=error&message=Invalid state"
            )
        )

    app_id = os.getenv("INSTAGRAM_APP_ID")
    app_secret = os.getenv("INSTAGRAM_APP_SECRET")
    redirect_uri = os.getenv("INSTAGRAM_REDIRECT_URI")

    if not app_id or not app_secret or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="Instagram OAuth configuration is incomplete"
        )

    # --------------------------------------------------------
    # Exchange code for token
    # --------------------------------------------------------

    token_response = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30
    )

    if token_response.status_code != 200:
        print(
            "Instagram token exchange failed:",
            token_response.status_code
        )

        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"instagram=error&message=Token exchange failed"
            )
        )

    token_data = _instagram_response_data(token_response.json())

    access_token = token_data.get("access_token")
    instagram_user_id = token_data.get("user_id")

    if not access_token:
        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"instagram=error&message=Access token missing"
            )
        )

    # --------------------------------------------------------
    # Get Instagram profile
    # --------------------------------------------------------

    profile_response = requests.get(
        "https://graph.instagram.com/me",
        params={
            "fields": "user_id,username",
            "access_token": access_token
        },
        timeout=30
    )

    if profile_response.status_code != 200:
        print(
            "Instagram profile lookup failed:",
            profile_response.status_code
        )

        return RedirectResponse(
            url=(
                f"{FRONTEND_URL}/social-accounts?"
                f"instagram=error&message=Unable to get Instagram profile"
            )
        )

    profile_data = _instagram_response_data(profile_response.json())

    instagram_id = profile_data.get("user_id") or instagram_user_id
    username = profile_data.get("username") or str(instagram_id)

    # --------------------------------------------------------
    # Save / update account
    # --------------------------------------------------------

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == "instagram"
        )
        .first()
    )

    if account:
        account.username = f"@{username}"
        account.access_token = access_token
        account.channel_id = instagram_id

    else:
        account = SocialAccount(
            user_id=user_id,
            platform="instagram",
            username=f"@{username}",
            access_token=access_token,
            channel_id=instagram_id
        )

        db.add(account)

    db.commit()
    db.refresh(account)

    return RedirectResponse(
        url=(
            f"{FRONTEND_URL}/social-accounts?"
            f"instagram=connected&account_id={account.id}"
        )
    )


# ============================================================
# FACEBOOK
# ============================================================

@router.get("/facebook/login")
def facebook_login(
    current_user_id: int = Depends(get_current_user),
    frontend_origin: str | None = None
):

    facebook_app_id = os.getenv("FACEBOOK_APP_ID")
    facebook_app_secret = os.getenv("FACEBOOK_APP_SECRET")
    facebook_config_id = os.getenv("FACEBOOK_CONFIG_ID")
    facebook_redirect_uri = os.getenv("FACEBOOK_REDIRECT_URI")

    if not facebook_app_id:
        raise HTTPException(
            status_code=500,
            detail="FACEBOOK_APP_ID is not configured"
        )

    if not facebook_app_secret:
        raise HTTPException(
            status_code=500,
            detail="FACEBOOK_APP_SECRET is not configured"
        )

    if not facebook_config_id:
        raise HTTPException(
            status_code=500,
            detail="FACEBOOK_CONFIG_ID is not configured"
        )

    if not facebook_redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="FACEBOOK_REDIRECT_URI is not configured"
        )

    frontend_origin = validate_frontend_origin(frontend_origin)
    random_state = secrets.token_urlsafe(32)

    state = generate_oauth_state(
        current_user_id,
        random_state,
        facebook_app_secret,
        frontend_origin
    )

    params = {
        "client_id": facebook_app_id,
        "redirect_uri": facebook_redirect_uri,
        "config_id": facebook_config_id,
        "response_type": "code",
        "state": state
    }

    authorization_url = (
        "https://www.facebook.com/v23.0/dialog/oauth?"
        + urlencode(params)
    )

    return {
        "authorization_url": authorization_url
    }


@router.get("/facebook/callback")
def facebook_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db)
):

    print("FACEBOOK CALLBACK STARTED")

    facebook_app_id = os.getenv("FACEBOOK_APP_ID")
    facebook_app_secret = os.getenv("FACEBOOK_APP_SECRET")
    facebook_redirect_uri = os.getenv("FACEBOOK_REDIRECT_URI")
    callback_frontend_url = FRONTEND_URL

    state_data = (
        verify_oauth_state(state, facebook_app_secret)
        if state and facebook_app_secret
        else (None, None, None)
    )
    user_id, random_state, state_frontend_origin = state_data
    if state_frontend_origin:
        callback_frontend_url = validate_frontend_origin(
            state_frontend_origin
        )

    def redirect_to_frontend(**query_params):
        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"{urlencode(query_params)}"
            )
        )

    if error:
        message = error_description or error
        return redirect_to_frontend(facebook="error", message=message)

    if not user_id or not random_state:
        return redirect_to_frontend(
            facebook="error",
            message="Invalid state"
        )

    if not code:
        return redirect_to_frontend(
            facebook="error",
            message="Invalid callback"
        )

    if (
        not facebook_app_id
        or not facebook_app_secret
        or not facebook_redirect_uri
    ):
        raise HTTPException(
            status_code=500,
            detail="Facebook OAuth configuration is incomplete"
        )

    # --------------------------------------------------------
    # Exchange code for user access token
    # --------------------------------------------------------

    token_response = requests.get(
        "https://graph.facebook.com/v23.0/oauth/access_token",
        params={
            "client_id": facebook_app_id,
            "client_secret": facebook_app_secret,
            "redirect_uri": facebook_redirect_uri,
            "code": code,
        },
        timeout=30
    )

    print(
        "Facebook token exchange status:",
        token_response.status_code
    )

    if token_response.status_code != 200:
        return redirect_to_frontend(
            facebook="error",
            message="Token exchange failed"
        )

    token_data = token_response.json()

    user_access_token = token_data.get("access_token")

    if not user_access_token:
        return redirect_to_frontend(
            facebook="error",
            message="User access token missing"
        )

    # --------------------------------------------------------
    # Get Facebook pages
    # --------------------------------------------------------

    pages_response = requests.get(
        "https://graph.facebook.com/v23.0/me/accounts",
        params={
            "fields": "id,name,access_token,tasks",
            "access_token": user_access_token,
        },
        timeout=30
    )

    print(
        "Facebook Pages response status:",
        pages_response.status_code
    )

    if pages_response.status_code != 200:
        return redirect_to_frontend(
            facebook="error",
            message="Unable to retrieve Pages"
        )

    pages_data = pages_response.json()

    pages = pages_data.get("data", [])

    if not pages:
        return redirect_to_frontend(
            facebook="error",
            message="No Facebook Page found"
        )

    # --------------------------------------------------------
    # Select first available Page
    # --------------------------------------------------------

    selected_page = pages[0]

    page_id = selected_page.get("id")
    page_name = selected_page.get("name")
    page_access_token = selected_page.get("access_token")

    tasks = selected_page.get("tasks", [])

    print("Facebook Page found:", page_name)
    print("Facebook Page ID:", page_id)

    if not page_access_token:
        return redirect_to_frontend(
            facebook="error",
            message="Page access token missing"
        )

    # --------------------------------------------------------
    # Save / update account
    # --------------------------------------------------------

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == "facebook"
        )
        .first()
    )

    if account:
        account.username = page_name
        account.access_token = page_access_token
        account.page_id = page_id

    else:
        account = SocialAccount(
            user_id=user_id,
            platform="facebook",
            username=page_name,
            access_token=page_access_token,
            page_id=page_id
        )

        db.add(account)

    db.commit()
    db.refresh(account)

    return redirect_to_frontend(
        facebook="connected",
        account_id=str(account.id)
    )


# ============================================================
# X / TWITTER OAUTH 2.0
# ============================================================

def generate_x_code_verifier(
    random_state: str,
    client_secret: str
) -> str:

    return hmac.new(
        client_secret.encode("utf-8"),
        random_state.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def generate_x_code_challenge(
    code_verifier: str
) -> str:

    digest = hashlib.sha256(
        code_verifier.encode("utf-8")
    ).digest()

    return (
        base64.urlsafe_b64encode(digest)
        .decode("utf-8")
        .rstrip("=")
    )


def generate_oauth_state(
    user_id: int,
    random_state: str,
    signing_secret: str,
    frontend_origin: str | None = None
) -> str:

    encoded_origin = (
        base64.urlsafe_b64encode(frontend_origin.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
        if frontend_origin
        else ""
    )
    state_payload = f"{user_id}:{random_state}:{encoded_origin}"

    signature = hmac.new(
        signing_secret.encode("utf-8"),
        state_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return f"{state_payload}:{signature}"


def verify_oauth_state(
    state: str,
    signing_secret: str
):

    try:
        state_payload, received_signature = state.rsplit(":", 1)

        user_id_text, random_state, encoded_origin = state_payload.split(":", 2)

        expected_signature = hmac.new(
            signing_secret.encode("utf-8"),
            state_payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            received_signature,
            expected_signature
        ):
            return None, None, None

        user_id = int(user_id_text)
        frontend_origin = None
        if encoded_origin:
            padded_origin = encoded_origin + "=" * (-len(encoded_origin) % 4)
            frontend_origin = base64.urlsafe_b64decode(
                padded_origin
            ).decode("utf-8")

        return user_id, random_state, frontend_origin

    except (ValueError, AttributeError, UnicodeDecodeError):
        return None, None, None


def validate_frontend_origin(frontend_origin: str | None) -> str:
    """Restrict the OAuth return host to configured frontend origins."""
    requested = frontend_origin or FRONTEND_URL
    parsed_requested = urlsplit(requested)

    if (
        parsed_requested.scheme not in {"http", "https"}
        or not parsed_requested.netloc
        or parsed_requested.username
        or parsed_requested.password
        or parsed_requested.path not in {"", "/"}
        or parsed_requested.query
        or parsed_requested.fragment
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid frontend origin"
        )

    requested_origin = (
        f"{parsed_requested.scheme}://{parsed_requested.netloc}"
    )
    configured_urls = [
        FRONTEND_URL,
        *os.getenv("FRONTEND_URLS", "").split(",")
    ]

    allowed_origins = set()
    for configured_url in configured_urls:
        configured = urlsplit(configured_url.strip())
        if configured.scheme in {"http", "https"} and configured.netloc:
            allowed_origins.add(
                f"{configured.scheme}://{configured.netloc}"
            )

    if requested_origin not in allowed_origins:
        raise HTTPException(
            status_code=400,
            detail=(
                "This frontend origin is not allowed for OAuth. "
                "Add it to FRONTEND_URL or FRONTEND_URLS."
            )
        )

    return requested_origin


# ------------------------------------------------------------
# X LOGIN
# ------------------------------------------------------------

@router.get("/x/login")
def x_login(
    current_user_id: int = Depends(get_current_user),
    frontend_origin: str | None = None
):

    x_client_id = os.getenv("X_CLIENT_ID")
    x_client_secret = os.getenv("X_CLIENT_SECRET")
    x_redirect_uri = os.getenv("X_REDIRECT_URI")

    if not x_client_id:
        raise HTTPException(
            status_code=500,
            detail="X_CLIENT_ID is not configured"
        )

    if not x_client_secret:
        raise HTTPException(
            status_code=500,
            detail="X_CLIENT_SECRET is not configured"
        )

    if not x_redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="X_REDIRECT_URI is not configured"
        )

    # --------------------------------------------------------
    # Generate state
    # --------------------------------------------------------

    random_state = secrets.token_urlsafe(32)
    frontend_origin = validate_frontend_origin(frontend_origin)

    state = generate_oauth_state(
        current_user_id,
        random_state,
        x_client_secret,
        frontend_origin
    )

    # --------------------------------------------------------
    # PKCE
    # --------------------------------------------------------

    code_verifier = generate_x_code_verifier(
        random_state,
        x_client_secret
    )

    code_challenge = generate_x_code_challenge(
        code_verifier
    )

    # --------------------------------------------------------
    # Required scopes
    # --------------------------------------------------------

    scopes = (
        "tweet.read "
        "tweet.write "
        "users.read "
        "offline.access"
    )

    params = {
        "response_type": "code",
        "client_id": x_client_id,
        "redirect_uri": x_redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    authorization_url = (
        "https://x.com/i/oauth2/authorize?"
        + urlencode(params)
    )

    return {
        "authorization_url": authorization_url
    }


# ------------------------------------------------------------
# X CALLBACK
# ------------------------------------------------------------

@router.get("/x/callback")
def x_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db)
):

    print("X CALLBACK STARTED")
    callback_frontend_url = FRONTEND_URL

    if state:
        x_client_secret = os.getenv("X_CLIENT_SECRET")
        if x_client_secret:
            _, _, state_frontend_origin = verify_oauth_state(
                state,
                x_client_secret
            )
            if state_frontend_origin:
                callback_frontend_url = state_frontend_origin

    # --------------------------------------------------------
    # Handle X errors
    # --------------------------------------------------------

    if error:
        message = error_description or error

        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message={message}"
            )
        )

    if not code:
        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message=Authorization code missing"
            )
        )

    if not state:
        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message=State missing"
            )
        )

    # --------------------------------------------------------
    # Get X configuration
    # --------------------------------------------------------

    x_client_id = os.getenv("X_CLIENT_ID")
    x_client_secret = os.getenv("X_CLIENT_SECRET")
    x_redirect_uri = os.getenv("X_REDIRECT_URI")

    if not x_client_id:
        raise HTTPException(
            status_code=500,
            detail="X_CLIENT_ID is not configured"
        )

    if not x_client_secret:
        raise HTTPException(
            status_code=500,
            detail="X_CLIENT_SECRET is not configured"
        )

    if not x_redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="X_REDIRECT_URI is not configured"
        )

    # --------------------------------------------------------
    # Verify state
    # --------------------------------------------------------

    user_id, random_state, state_frontend_origin = verify_oauth_state(
        state,
        x_client_secret
    )

    if not user_id or not random_state:
        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message=Invalid state"
            )
        )

    callback_frontend_url = state_frontend_origin or callback_frontend_url

    # --------------------------------------------------------
    # Recreate PKCE verifier
    # --------------------------------------------------------

    code_verifier = generate_x_code_verifier(
        random_state,
        x_client_secret
    )

    # --------------------------------------------------------
    # Exchange authorization code for tokens
    # --------------------------------------------------------

    token_url = "https://api.x.com/2/oauth2/token"

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": x_redirect_uri,
        "code_verifier": code_verifier,
    }

    token_response = requests.post(
        token_url,
        data=token_data,
        auth=(x_client_id, x_client_secret),
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        timeout=30
    )

    print(
        "X token exchange status:",
        token_response.status_code
    )

    if token_response.status_code != 200:

        try:
            error_data = token_response.json()

            print(
                "X token exchange error:",
                error_data.get("error")
            )

        except Exception:
            pass

        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message=Token exchange failed"
            )
        )

    token_json = token_response.json()

    access_token = token_json.get("access_token")
    refresh_token = token_json.get("refresh_token")

    if not access_token:
        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message=X access token missing"
            )
        )

    # --------------------------------------------------------
    # Get X user profile
    # --------------------------------------------------------

    user_response = requests.get(
        "https://api.x.com/2/users/me",
        headers={
            "Authorization": f"Bearer {access_token}"
        },
        params={
            "user.fields": (
                "id,name,username,profile_image_url"
            )
        },
        timeout=30
    )

    print(
        "X user information status:",
        user_response.status_code
    )

    if user_response.status_code != 200:

        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message=Unable to get X profile"
            )
        )

    user_json = user_response.json()

    x_user = user_json.get("data")

    if not x_user:
        return RedirectResponse(
            url=(
                f"{callback_frontend_url}/social-accounts?"
                f"twitter=error&message=X profile not found"
            )
        )

    x_user_id = x_user.get("id")
    x_username = x_user.get("username")
    x_name = x_user.get("name")

    if x_username:
        username = f"@{x_username}"
    else:
        username = x_name or x_user_id

    # --------------------------------------------------------
    # Save / update X account
    #
    # We keep platform="twitter" because the existing
    # SocialPilot frontend/backend uses "twitter".
    # --------------------------------------------------------

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == "twitter"
        )
        .first()
    )

    if account:

        account.username = username
        account.access_token = access_token
        account.channel_id = x_user_id

        if refresh_token:
            account.refresh_token = refresh_token

    else:

        account = SocialAccount(
            user_id=user_id,
            platform="twitter",
            username=username,
            access_token=access_token,
            refresh_token=refresh_token,
            channel_id=x_user_id
        )

        db.add(account)

    db.commit()
    db.refresh(account)

    print(
        "X account connected successfully:",
        username
    )

    return RedirectResponse(
        url=(
            f"{callback_frontend_url}/social-accounts?"
            f"twitter=connected&account_id={account.id}"
        )
    )


# ============================================================
# ADD SOCIAL ACCOUNT
# ============================================================

@router.post("/")
def add_social_account(
    platform: str,
    username: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
    channel_id: str | None = None,
    page_id: str | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    supported_platforms = [
        "instagram",
        "facebook",
        "linkedin",
        "twitter",
        "youtube"
    ]

    if platform not in supported_platforms:
        raise HTTPException(
            status_code=400,
            detail="Unsupported social media platform"
        )

    existing_account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == current_user_id,
            SocialAccount.platform == platform
        )
        .first()
    )

    if existing_account:
        raise HTTPException(
            status_code=400,
            detail=f"{platform} account already exists"
        )

    account = SocialAccount(
        user_id=current_user_id,
        platform=platform,
        username=username,
        access_token=access_token,
        refresh_token=refresh_token,
        channel_id=channel_id,
        page_id=page_id
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    return {
        "message": "Social account added successfully",
        "account": {
            "id": account.id,
            "platform": account.platform,
            "username": account.username
        }
    }


# ============================================================
# GET SOCIAL ACCOUNTS
# ============================================================

@router.get("/")
def get_social_accounts(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    accounts = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == current_user_id
        )
        .all()
    )

    return [
        {
            "id": account.id,
            "platform": account.platform,
            "username": account.username,
            "channel_id": account.channel_id,
            "page_id": account.page_id,
            "connected": bool(account.access_token)
        }
        for account in accounts
    ]


# ============================================================
# CONNECT ACCOUNT
# ============================================================

@router.put("/{account_id}/connect")
def connect_social_account(
    account_id: int,
    access_token: str,
    refresh_token: str | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.id == account_id,
            SocialAccount.user_id == current_user_id
        )
        .first()
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Social account not found"
        )

    account.access_token = access_token

    if refresh_token:
        account.refresh_token = refresh_token

    db.commit()
    db.refresh(account)

    return {
        "message": "Social account connected successfully",
        "account": {
            "id": account.id,
            "platform": account.platform,
            "username": account.username,
            "connected": True
        }
    }


# ============================================================
# DISCONNECT ACCOUNT
# ============================================================

@router.put("/{account_id}/disconnect")
def disconnect_social_account(
    account_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.id == account_id,
            SocialAccount.user_id == current_user_id
        )
        .first()
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Social account not found"
        )

    account.access_token = None
    account.refresh_token = None

    db.commit()

    return {
        "message": "Social account disconnected successfully"
    }


# ============================================================
# DELETE ACCOUNT
# ============================================================

@router.delete("/{account_id}")
def delete_social_account(
    account_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.id == account_id,
            SocialAccount.user_id == current_user_id
        )
        .first()
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Social account not found"
        )

    db.delete(account)
    db.commit()

    return {
        "message": "Social account deleted successfully"
    }