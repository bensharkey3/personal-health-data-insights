"""Shared-secret check for public function URLs (webhook, Tasker). The caller sends the secret,
scheme included (e.g. "Bearer <random>"), in the Authorization header; the expected value lives
in an SSM SecureString created by hand (D15) and is cached for the life of the container."""

import hmac

_cache: dict[str, str] = {}


def authorised(headers: dict, ssm, param: str) -> bool:
    if param not in _cache:
        _cache[param] = ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    # Function URLs lower-case header names. compare_digest avoids leaking the secret by timing.
    return hmac.compare_digest(headers.get("authorization", ""), _cache[param])
