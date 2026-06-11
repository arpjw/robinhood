import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

TOKEN_CACHE_PATH = Path.home() / ".robinhood_mcp_token.json"
_AUTH_METADATA_URL = "https://agent.robinhood.com/.well-known/oauth-authorization-server/mcp/trading"
_TOKEN_ENDPOINT = "https://api.robinhood.com/oauth2/token/"
_EXPIRY_BUFFER_SECONDS = 60


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _fetch_metadata() -> dict:
    with urllib.request.urlopen(_AUTH_METADATA_URL, timeout=10) as resp:
        return json.loads(resp.read())


def _post_token(payload: dict) -> dict:
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(_TOKEN_ENDPOINT, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    data["expires_at"] = time.time() + data.get("expires_in", 3600)
    return data


def load_cached_token() -> Optional[dict]:
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE_PATH.read_text())
        if "access_token" not in data or "expires_at" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_token(token_data: dict) -> None:
    TOKEN_CACHE_PATH.write_text(json.dumps(token_data, indent=2))
    TOKEN_CACHE_PATH.chmod(0o600)


def _is_expired(token_data: dict) -> bool:
    return token_data.get("expires_at", 0) < time.time() + _EXPIRY_BUFFER_SECONDS


def _refresh(token_data: dict, client_id: str) -> dict:
    refresh_tok = token_data.get("refresh_token")
    if not refresh_tok:
        raise RuntimeError("no refresh token in cache")
    new_data = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
            "client_id": client_id,
        }
    )
    if "refresh_token" not in new_data:
        new_data["refresh_token"] = refresh_tok
    return new_data


def _pkce_flow(client_id: str) -> dict:
    metadata = _fetch_metadata()
    authorization_endpoint = metadata.get("authorization_endpoint")
    if not authorization_endpoint:
        raise RuntimeError("auth server metadata missing authorization_endpoint")

    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    port = _free_port()
    redirect_uri = f"http://localhost:{port}/callback"

    auth_url = authorization_endpoint + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "trading",
        }
    )

    received: dict = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received["code"] = params.get("code", [None])[0]
            received["state"] = params.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authentication complete. You may close this tab.</h2></body></html>"
            )

        def log_message(self, *args) -> None:
            pass

    print("Opening browser for Robinhood OAuth2 authorization...")
    print(f"If the browser does not open, visit:\n  {auth_url}")
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", port), _Handler)
    server.handle_request()
    server.server_close()

    if not received.get("code"):
        raise RuntimeError("no authorization code received from callback")
    if received.get("state") != state:
        raise RuntimeError("OAuth2 state mismatch — possible CSRF")

    return _post_token(
        {
            "grant_type": "authorization_code",
            "code": received["code"],
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
    )


def get_valid_token() -> str:
    client_id = os.getenv("ROBINHOOD_CLIENT_ID")
    if not client_id:
        raise RuntimeError(
            "ROBINHOOD_CLIENT_ID is required for OAuth2 PKCE authentication. "
            "Set it with: export ROBINHOOD_CLIENT_ID=<your_client_id>"
        )

    cached = load_cached_token()
    if cached and not _is_expired(cached):
        return cached["access_token"]

    if cached and cached.get("refresh_token"):
        try:
            refreshed = _refresh(cached, client_id)
            save_token(refreshed)
            return refreshed["access_token"]
        except Exception as exc:
            print(f"Token refresh failed ({exc}), re-authenticating via browser...")

    token_data = _pkce_flow(client_id)
    save_token(token_data)
    return token_data["access_token"]
