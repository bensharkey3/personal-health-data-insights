"""JSON over HTTP, retrying 429 and 5xx with exponential backoff and jitter (D2)."""

import json
import random
import time
import urllib.error
from urllib.request import Request, urlopen

RETRIES = 5  # waits about 1, 2, 4, 8, 16 s: half a minute before giving up


def wait_for(e: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait: the server's Retry-After when it gives seconds, else 2^attempt + jitter."""
    try:
        return float(e.headers.get("Retry-After", ""))
    except ValueError:  # missing, or an HTTP date
        return 2**attempt + random.random()


def call(req: Request, timeout: int = 60, text: bool = False):
    """The parsed JSON reply, or the body as text when `text` is set (e.g. a bare token)."""
    for attempt in range(RETRIES + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode().strip() if text else json.load(resp)
        except urllib.error.HTTPError as e:
            if attempt == RETRIES or not (e.code == 429 or e.code >= 500):
                raise
            wait = wait_for(e, attempt)
            print(f"HTTP {e.code}, retry {attempt + 1} in {wait:.1f} s")
            time.sleep(wait)
    raise AssertionError("unreachable")  # the loop always returns or raises
