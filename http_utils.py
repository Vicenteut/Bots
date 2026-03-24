from __future__ import annotations

import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from config import get_bool_env, get_optional_float, get_optional_int

DEFAULT_TIMEOUT = get_optional_int("HTTP_TIMEOUT_SECONDS", 30) or 30
DEFAULT_RETRIES = get_optional_int("HTTP_MAX_RETRIES", 3) or 3
DEFAULT_BACKOFF = get_optional_float("HTTP_BACKOFF_SECONDS", 1.5) or 1.5
DEFAULT_SSL_VERIFY = get_bool_env("HTTP_VERIFY_SSL", True)


def build_ssl_context(*, verify: bool | None = None) -> ssl.SSLContext:
    ssl_verify = DEFAULT_SSL_VERIFY if verify is None else verify
    if ssl_verify:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _sleep_backoff(attempt: int, backoff_seconds: float) -> None:
    delay = backoff_seconds * (2 ** max(attempt - 1, 0))
    jitter = random.uniform(0, max(backoff_seconds / 2, 0.1))
    time.sleep(delay + jitter)


def retry_call(
    func: Callable[[], Any],
    *,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
    should_retry: Callable[[Exception], bool] | None = None,
) -> Any:
    last_error: Exception | None = None
    total_attempts = max(retries, 1)
    for attempt in range(1, total_attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            retry_allowed = attempt < total_attempts
            if should_retry is not None and not should_retry(exc):
                raise
            if not retry_allowed:
                raise
            _sleep_backoff(attempt, backoff_seconds)
    if last_error is not None:
        raise last_error


def is_retryable_http_error(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or error.code >= 500
    if isinstance(error, urllib.error.URLError):
        return True
    if isinstance(error, TimeoutError):
        return True
    return False


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    data: bytes | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
    ssl_context: ssl.SSLContext | None = None,
) -> Any:
    encoded_data = data
    request_headers = dict(headers or {})
    if payload is not None and data is not None:
        raise ValueError("Use either payload or data, not both")
    if payload is not None:
        encoded_data = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    context = ssl_context if ssl_context is not None else build_ssl_context()

    def _make_request():
        request = urllib.request.Request(
            url,
            data=encoded_data,
            headers=request_headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))

    return retry_call(
        _make_request,
        retries=retries,
        backoff_seconds=backoff_seconds,
        should_retry=is_retryable_http_error,
    )


def post_form_json(
    url: str,
    params: dict[str, Any],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
    ssl_context: ssl.SSLContext | None = None,
) -> Any:
    data = urllib.parse.urlencode(params).encode("utf-8")
    return request_json(
        url,
        method="POST",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
        retries=retries,
        backoff_seconds=backoff_seconds,
        ssl_context=ssl_context,
    )
