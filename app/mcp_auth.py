"""OAuth 2.0 authorization + resource server for the ``/mcp`` endpoint.

MCP clients (claude.ai, Claude Code CLI, Codex) connect as OAuth clients and
expect the server to support Dynamic Client Registration + the authorization
code flow with PKCE. This module implements that on top of Voice Message
Studio's existing Google login, and persists issued clients / refresh tokens in
a small SQLite database (``mcp_oauth.db`` under ``DATA_DIR``) so a user
authenticates **once per account** and is never prompted again (refresh tokens
survive restarts and redeploys).

The heavy lifting (PKCE verification, redirect_uri matching, code expiry, the
``/authorize`` `/token` `/register` `/.well-known` routes) is done by the MCP
SDK; this module only implements the ``OAuthAuthorizationServerProvider``
storage/minting protocol plus a small login page that reuses
``verify_google_credential``.

The app is otherwise file-based, so this module owns its own tiny SQLite store
rather than sharing a coordinator database (as the Mailcheck MCP server does).
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl

from app.auth import verify_google_credential
from app.config import get_settings

settings = get_settings()

PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "https://voice.basisvps.com").rstrip("/")
LOGIN_PATH = "/oauth/voicestudio/login"
COMPLETE_PATH = "/oauth/voicestudio/complete"

ACCESS_TOKEN_TTL = 3600  # seconds
CODE_TTL = 300  # seconds
DEFAULT_SCOPES = ["voicestudio"]


# --- token subclasses that also carry the resolved end-user identity ---------
# (FastMCP never serializes these to the client, so extra fields are safe.)
class _AuthCode(AuthorizationCode):
    user_email: str
    user_sub: str


class _Refresh(RefreshToken):
    user_email: str
    user_sub: str


class _Access(AccessToken):
    user_email: str
    user_sub: str


# --- minimal SQLite store ----------------------------------------------------
# This app has no shared database, so the MCP server keeps its own tiny store
# for OAuth clients, pending requests, codes, and tokens.
class _OAuthStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        # ``check_same_thread=False`` + a lock: the MCP SDK touches these tables
        # from the anyio worker threads that serve /token, /authorize, etc.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    client_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_pending (
                    rid TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_codes (
                    code TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_refresh (
                    token TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    user_email TEXT NOT NULL,
                    user_sub TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_access (
                    token TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    user_email TEXT NOT NULL,
                    user_sub TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()


_store: _OAuthStore | None = None


def _db() -> _OAuthStore:
    if _store is None:  # pragma: no cover - build_auth() initializes it first
        raise RuntimeError("OAuth store not initialized; call build_auth() first")
    return _store


class VoiceStudioOAuthProvider(
    OAuthAuthorizationServerProvider[_AuthCode, _Refresh, _Access]
):
    # --- Dynamic Client Registration -------------------------------------
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = _db().fetchone("SELECT client_json FROM oauth_clients WHERE client_id=?", (client_id,))
        if not row:
            return None
        return OAuthClientInformationFull.model_validate_json(row["client_json"])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        _db().execute(
            "INSERT OR REPLACE INTO oauth_clients (client_id, client_json) VALUES (?, ?)",
            (client_info.client_id, client_info.model_dump_json()),
        )

    # --- Authorization: hand off to the login page -----------------------
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        rid = secrets.token_urlsafe(24)
        _db().execute(
            "INSERT INTO oauth_pending (rid, data_json, created_at) VALUES (?, ?, ?)",
            (
                rid,
                json.dumps(
                    {
                        "client_id": client.client_id,
                        "redirect_uri": str(params.redirect_uri),
                        "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                        "code_challenge": params.code_challenge,
                        "scopes": params.scopes or DEFAULT_SCOPES,
                        "state": params.state,
                        "resource": params.resource,
                    }
                ),
                time.time(),
            ),
        )
        return f"{LOGIN_PATH}?rid={rid}"

    # --- Authorization code ----------------------------------------------
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> _AuthCode | None:
        row = _db().fetchone(
            "SELECT data_json, expires_at FROM oauth_codes WHERE code=?", (authorization_code,)
        )
        if not row:
            return None
        data = json.loads(row["data_json"])
        return _AuthCode(
            code=authorization_code,
            scopes=data["scopes"],
            expires_at=row["expires_at"],
            client_id=data["client_id"],
            code_challenge=data["code_challenge"],
            redirect_uri=AnyUrl(data["redirect_uri"]),
            redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
            resource=data.get("resource"),
            user_email=data["user_email"],
            user_sub=data["user_sub"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: _AuthCode
    ) -> OAuthToken:
        # One-time use: consume the code.
        _db().execute("DELETE FROM oauth_codes WHERE code=?", (authorization_code.code,))
        return self._issue_tokens(
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            user_email=authorization_code.user_email,
            user_sub=authorization_code.user_sub,
            refresh_token=None,
        )

    # --- Refresh token ----------------------------------------------------
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> _Refresh | None:
        row = _db().fetchone("SELECT * FROM oauth_refresh WHERE token=?", (refresh_token,))
        if not row:
            return None
        return _Refresh(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=json.loads(row["scopes_json"]),
            expires_at=None,
            user_email=row["user_email"],
            user_sub=row["user_sub"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: _Refresh,
        scopes: list[str],
    ) -> OAuthToken:
        # Keep the same long-lived refresh token; issue a fresh access token.
        return self._issue_tokens(
            client_id=refresh_token.client_id,
            scopes=scopes or refresh_token.scopes,
            user_email=refresh_token.user_email,
            user_sub=refresh_token.user_sub,
            refresh_token=refresh_token.token,
        )

    # --- Access token verification ---------------------------------------
    async def load_access_token(self, token: str) -> _Access | None:
        row = _db().fetchone("SELECT * FROM oauth_access WHERE token=?", (token,))
        if not row:
            return None
        if row["expires_at"] < time.time():
            _db().execute("DELETE FROM oauth_access WHERE token=?", (token,))
            return None
        return _Access(
            token=token,
            client_id=row["client_id"],
            scopes=json.loads(row["scopes_json"]),
            expires_at=int(row["expires_at"]),
            user_email=row["user_email"],
            user_sub=row["user_sub"],
        )

    async def revoke_token(self, token: _Access | _Refresh) -> None:
        _db().execute("DELETE FROM oauth_access WHERE token=?", (token.token,))
        _db().execute("DELETE FROM oauth_refresh WHERE token=?", (token.token,))

    # --- helpers ----------------------------------------------------------
    def _issue_tokens(
        self,
        client_id: str,
        scopes: list[str],
        user_email: str,
        user_sub: str,
        refresh_token: str | None,
    ) -> OAuthToken:
        access_token = secrets.token_urlsafe(32)
        expires_at = time.time() + ACCESS_TOKEN_TTL
        _db().execute(
            """
            INSERT OR REPLACE INTO oauth_access
                (token, client_id, scopes_json, user_email, user_sub, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (access_token, client_id, json.dumps(scopes), user_email, user_sub, expires_at),
        )
        if refresh_token is None:
            refresh_token = secrets.token_urlsafe(32)
            _db().execute(
                """
                INSERT OR REPLACE INTO oauth_refresh
                    (token, client_id, scopes_json, user_email, user_sub)
                VALUES (?, ?, ?, ?, ?)
                """,
                (refresh_token, client_id, json.dumps(scopes), user_email, user_sub),
            )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh_token,
        )


provider = VoiceStudioOAuthProvider()


# --- login routes (mounted on the FastAPI app so SessionMiddleware applies) ---
oauth_router = APIRouter()


def _load_pending(rid: str) -> dict:
    row = _db().fetchone("SELECT data_json FROM oauth_pending WHERE rid=?", (rid,))
    if not row:
        raise HTTPException(status_code=400, detail="Unknown or expired authorization request")
    return json.loads(row["data_json"])


def _finish(rid: str, pending: dict, user: dict[str, str]) -> RedirectResponse:
    code = secrets.token_urlsafe(24)
    data = dict(pending)
    data["user_email"] = user["email"]
    data["user_sub"] = user["sub"]
    _db().execute(
        "INSERT INTO oauth_codes (code, data_json, expires_at) VALUES (?, ?, ?)",
        (code, json.dumps(data), time.time() + CODE_TTL),
    )
    _db().execute("DELETE FROM oauth_pending WHERE rid=?", (rid,))
    url = construct_redirect_uri(pending["redirect_uri"], code=code, state=pending.get("state"))
    return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": "no-store"})


_LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authorize Voice Studio MCP</title>
<script src="https://accounts.google.com/gsi/client" async defer></script>
<style>
  body{{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;
       display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
  .card{{background:#1e293b;padding:2.5rem;border-radius:12px;max-width:380px;text-align:center;
         box-shadow:0 10px 30px rgba(0,0,0,.4)}}
  h1{{font-size:1.25rem;margin:0 0 .5rem}} p{{color:#94a3b8;font-size:.9rem;margin:0 0 1.5rem}}
  .btn{{display:inline-block;margin-top:1rem}}
</style></head>
<body><div class="card">
  <h1>Authorize Voice Studio</h1>
  <p>Sign in with Google to let this MCP client generate voice notes on your behalf.</p>
  <div id="g_id_onload" data-client_id="{client_id}" data-callback="onCredential" data-auto_prompt="false"></div>
  <div class="g_id_signin btn" data-type="standard" data-size="large" data-theme="filled_blue"></div>
  <form id="f" method="post" action="{complete}">
    <input type="hidden" name="rid" value="{rid}">
    <input type="hidden" name="credential" id="cred">
  </form>
  <script>
    function onCredential(resp){{
      document.getElementById('cred').value = resp.credential;
      document.getElementById('f').submit();
    }}
  </script>
</div></body></html>
"""


@oauth_router.get(LOGIN_PATH, include_in_schema=False)
async def oauth_login(rid: str, request: Request):
    pending = _load_pending(rid)

    # Development mode: no Google, auto-issue for the local developer.
    if settings.auth_mode == "development":
        user = {"sub": "local-development-user", "email": "developer@localhost"}
        return _finish(rid, pending, user)

    # Reuse an existing browser session if the user is already signed in.
    session_user = request.session.get("user")
    if session_user and session_user.get("email"):
        return _finish(rid, pending, session_user)

    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="Google login is not configured")
    return HTMLResponse(
        _LOGIN_PAGE.format(client_id=settings.google_client_id, complete=COMPLETE_PATH, rid=rid)
    )


@oauth_router.post(COMPLETE_PATH, include_in_schema=False)
async def oauth_complete(request: Request, rid: str = Form(...), credential: str = Form(...)):
    pending = _load_pending(rid)
    user = verify_google_credential(credential, settings)
    request.session.clear()
    request.session["user"] = user
    return _finish(rid, pending, user)


def build_auth() -> tuple[VoiceStudioOAuthProvider | None, AuthSettings | None]:
    """Return the OAuth provider + settings, or (None, None) when auth is disabled.

    Set ``MCP_DISABLE_AUTH=1`` to run the MCP server unauthenticated (local
    testing only).
    """
    if os.environ.get("MCP_DISABLE_AUTH") == "1":
        return None, None
    global _store
    if _store is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _store = _OAuthStore(str(settings.data_dir / "mcp_oauth.db"))
    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(PUBLIC_URL),
        resource_server_url=AnyHttpUrl(f"{PUBLIC_URL}/mcp"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            default_scopes=DEFAULT_SCOPES,
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[],
    )
    return provider, auth_settings
