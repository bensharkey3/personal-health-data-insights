"""Google Health API proof of concept: sign in once, pull one day of steps, heart rate and sleep.

Runs on your laptop. Secrets and data stay outside the repo:
  ~/.config/health-insights/client_secret.json  OAuth "Desktop app" client from Google Cloud
  ~/.config/health-insights/token.json          refresh token, created on first run
  ~/health-poc/<type>-<date>.json               raw API responses

One-off setup in the Google Cloud console:
  1. Create a project and enable the "Google Health API".
  2. Google Auth Platform: consent screen in Personal mode if offered, else External with
     yourself as a test user. Add the three read-only scopes in SCOPES.
  3. Clients > Create client > Desktop app > download the JSON to the path above.

Usage: python3 src/ingest/google_health/poc.py [--date YYYY-MM-DD]   (default: yesterday)
"""

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

CONFIG = Path.home() / ".config" / "health-insights"
OUT = Path.home() / "health-poc"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://health.googleapis.com/v4/users/me/dataTypes"
SCOPES = " ".join(
    f"https://www.googleapis.com/auth/googlehealth.{s}.readonly"
    for s in ("activity_and_fitness", "health_metrics_and_measurements", "sleep")
)


def post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body)) as resp:
        return json.load(resp)


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

    tokens = post(
        TOKEN_URL,
        {
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code": params["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
        },
    )
    return tokens["refresh_token"]


def access_token(client: dict, refresh_token: str) -> str:
    try:
        return post(
            TOKEN_URL,
            {
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )["access_token"]
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Token refresh failed ({e.read().decode()}). Delete token.json and rerun."
        ) from None  # hide the HTTPError traceback; the message says it all


def day_filter(kind: str, day: date) -> str:
    """Filter for one local day. Steps match on start, sleep on end (civil = local time, no
    offset); heart rate is a sample type filtered on UTC time."""
    nxt = day + timedelta(days=1)
    if kind == "heart-rate":

        def utc(d: date) -> str:
            # .astimezone() on a naive datetime treats it as this computer's local time.
            local_midnight = datetime.combine(d, time()).astimezone()
            return local_midnight.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        field, lo, hi = "heart_rate.sample_time.physical_time", utc(day), utc(nxt)
    else:
        field = (
            "steps.interval.civil_start_time"
            if kind == "steps"
            else "sleep.interval.civil_end_time"
        )
        lo, hi = f"{day}T00:00:00", f"{nxt}T00:00:00"
    return f'{field} >= "{lo}" AND {field} < "{hi}"'


def fetch(kind: str, day: date, token: str) -> list[dict]:
    points: list[dict] = []
    page = None
    while True:
        query = {"filter": day_filter(kind, day), "pageSize": 5000}  # default 50, max 5,000
        query |= {"pageToken": page} if page else {}
        qs = urllib.parse.urlencode(query, quote_via=urllib.parse.quote)  # spaces as %20
        req = urllib.request.Request(
            f"{API}/{kind}/dataPoints?{qs}", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req) as resp:
            body = json.load(resp)
        points += body.get("dataPoints", [])
        if not (page := body.get("nextPageToken")):  # := assigns and tests in one step
            return points


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull one day of Google Health data.")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    day = parser.parse_args().date

    client = json.loads((CONFIG / "client_secret.json").read_text())["installed"]
    token_file = CONFIG / "token.json"
    if not token_file.exists():
        refresh_token = sign_in(client)
        token_file.touch(mode=0o600)  # owner-only before the secret is written
        token_file.write_text(json.dumps({"refresh_token": refresh_token}))
    token = access_token(client, json.loads(token_file.read_text())["refresh_token"])

    OUT.mkdir(exist_ok=True)
    for kind in ("steps", "heart-rate", "sleep"):
        try:
            points = fetch(kind, day, token)
        except urllib.error.HTTPError as e:
            print(f"{kind}: HTTP {e.code} {e.read().decode()[:300]}")
            continue
        (OUT / f"{kind}-{day}.json").write_text(json.dumps(points, indent=2))
        print(f"{kind}: {len(points)} data points")
    print(f"Raw JSON in {OUT}")


if __name__ == "__main__":
    main()
