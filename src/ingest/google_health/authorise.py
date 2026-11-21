"""One-off Google sign-in on the laptop to get a refresh token for the ingestion Lambda.

Reads ~/.config/health-insights/client_secret.json (OAuth "Desktop app" client from Google Cloud)
and writes the refresh token to ~/.config/health-insights/token.json, which is outside the repo.
The token is never printed. Copy both into SSM by hand (docs/specs/02-google-health-oauth.md).

Usage: py src/ingest/google_health/authorise.py
"""

import base64
import hashlib
import http.server
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CONFIG = Path.home() / ".config" / "health-insights"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = " ".join(
    f"https://www.googleapis.com/auth/googlehealth.{s}.readonly"
    for s in ("activity_and_fitness", "health_metrics_and_measurements", "sleep")
)


def sign_in(client: dict) -> str:
    """Browser consent with PKCE; returns a refresh token."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    params: dict[str, str] = {}

    # Tiny local web server that catches Google's redirect and keeps its query parameters.
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            params.update(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab.")

        def log_message(self, *args: object) -> None:  # silence request logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)  # port 0 = any free port
    redirect = f"http://127.0.0.1:{server.server_port}/"
    query = {
        "client_id": client["client_id"],
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",  # ask for a refresh token
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(query)}"
    print(f"Opening browser to sign in. If it doesn't open, visit:\n{url}")
    webbrowser.open(url)
    while "code" not in params and "error" not in params:  # skip e.g. favicon requests
        server.handle_request()
    if params.get("state") != state or "code" not in params:
        raise SystemExit(f"Sign-in failed: {params.get('error', 'state mismatch')}")

    form = {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "code": params["code"],
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
    }
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode())
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["refresh_token"]


def main() -> None:
    client = json.loads((CONFIG / "client_secret.json").read_text())["installed"]
    refresh_token = sign_in(client)
    token_file = CONFIG / "token.json"
    token_file.touch(mode=0o600)  # owner-only before the secret is written
    token_file.write_text(json.dumps({"refresh_token": refresh_token}))
    print(f"Refresh token saved to {token_file}")


if __name__ == "__main__":
    main()
