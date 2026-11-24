# SPDX-License-Identifier: Apache-2.0
"""Small HTTP client for the Olostep API (https://docs.olostep.com), shared by the components."""

from __future__ import annotations

import asyncio
import html
import re
import time
from typing import Any

import httpx
from haystack.utils import Secret

API_BASE = "https://api.olostep.com/v1"
USER_AGENT = "olostep-haystack"
RETRY_STATUS = {429, 502, 503, 504}
RETRIES = 2

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class OlostepError(Exception):
    """An Olostep API call failed."""


def resolve_key(api_key: Secret) -> str:
    """The API key's value, or a clear error when it isn't set."""
    value = api_key.resolve_value()
    if not value:
        raise OlostepError("Olostep API key is missing. Set OLOSTEP_API_KEY or pass api_key.")
    return str(value)


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": USER_AGENT}


def _message(response: httpx.Response) -> str:
    status = response.status_code
    if status == 401:
        return "Olostep rejected the API key (HTTP 401). Check OLOSTEP_API_KEY."
    if status == 402:
        return "The Olostep account is out of credits (HTTP 402)."
    if status == 429:
        return "Olostep rate limit reached (HTTP 429)."
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("detail") or body.get("message") or body.get("title") or "")
    except ValueError:
        pass
    return f"Olostep returned HTTP {status}" + (f": {detail}" if detail else "")


def _parse(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        raise OlostepError(_message(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise OlostepError("Olostep returned a response that is not JSON") from exc
    if not isinstance(data, dict):
        raise OlostepError("Olostep returned an unexpected response")
    return data


def request(
    method: str, path: str, api_key: str, timeout: float, *, json: Any = None, params: Any = None
) -> dict[str, Any]:
    """Call the API, retrying rate limits, gateway errors and network failures twice."""
    for attempt in range(RETRIES + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(method, API_BASE + path, json=json, params=params, headers=_headers(api_key))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == RETRIES:
                raise OlostepError(f"Could not reach Olostep: {exc}") from exc
        else:
            if response.status_code not in RETRY_STATUS or attempt == RETRIES:
                return _parse(response)
        time.sleep(2**attempt)
    raise OlostepError("Olostep request failed")  # unreachable


async def arequest(
    method: str, path: str, api_key: str, timeout: float, *, json: Any = None, params: Any = None
) -> dict[str, Any]:
    """Async version of :func:`request`."""
    for attempt in range(RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method, API_BASE + path, json=json, params=params, headers=_headers(api_key)
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == RETRIES:
                raise OlostepError(f"Could not reach Olostep: {exc}") from exc
        else:
            if response.status_code not in RETRY_STATUS or attempt == RETRIES:
                return _parse(response)
        await asyncio.sleep(2**attempt)
    raise OlostepError("Olostep request failed")  # unreachable


def page_title(html_content: str | None) -> str:
    """The page's <title>, or an empty string."""
    match = _TITLE.search(html_content or "")
    return html.unescape(" ".join(match.group(1).split())) if match else ""


def clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None or empty, so optional settings use the API defaults."""
    return {key: value for key, value in payload.items() if value not in (None, [], "")}
