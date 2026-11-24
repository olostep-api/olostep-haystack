# SPDX-License-Identifier: Apache-2.0
"""Wait for an Olostep crawl or batch and turn its pages into Haystack Documents."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from haystack import logging
from haystack.dataclasses import Document

from ._client import OlostepError, arequest, request

logger = logging.getLogger(__name__)

PAGE_SIZE = 100  # rows per listing call
CONTENT_CONCURRENCY = 10  # parallel content downloads in the async path

# kind -> (status path, listing path, rows key, extra listing params)
_JOBS = {
    "crawl": ("/crawls/{id}", "/crawls/{id}/pages", "pages", {}),
    "batch": ("/batches/{id}", "/batches/{id}/items", "items", {"status": "completed"}),
}


def _paths(kind: str, job_id: str) -> tuple[str, str, str, dict[str, Any]]:
    info, listing, key, params = _JOBS[kind]
    return info.format(id=job_id), listing.format(id=job_id), key, params


def _document(row: dict[str, Any], content: str, kind: str, job_id: str) -> Document:
    meta = {"url": row.get("url"), "source": "olostep", f"{kind}_id": job_id}
    if row.get("custom_id") is not None:
        meta["custom_id"] = row["custom_id"]
    return Document(content=content, meta=meta)


def wait(kind: str, job_id: str, status: str | None, api_key: str, timeout: float, wait_timeout: float, poll: float):
    """Poll until the job completes; raise OlostepError if it fails or runs past wait_timeout."""
    info_path = _paths(kind, job_id)[0]
    deadline = time.monotonic() + wait_timeout
    while status != "completed":
        if status == "failed":
            raise OlostepError(f"Olostep {kind} {job_id} failed")
        if time.monotonic() >= deadline:
            raise OlostepError(f"Olostep {kind} {job_id} is still {status} after {wait_timeout:.0f}s")
        time.sleep(poll)
        status = request("GET", info_path, api_key, timeout).get("status")


async def await_job(
    kind: str, job_id: str, status: str | None, api_key: str, timeout: float, wait_timeout: float, poll: float
):
    """Async version of :func:`wait`."""
    info_path = _paths(kind, job_id)[0]
    deadline = time.monotonic() + wait_timeout
    while status != "completed":
        if status == "failed":
            raise OlostepError(f"Olostep {kind} {job_id} failed")
        if time.monotonic() >= deadline:
            raise OlostepError(f"Olostep {kind} {job_id} is still {status} after {wait_timeout:.0f}s")
        await asyncio.sleep(poll)
        status = (await arequest("GET", info_path, api_key, timeout)).get("status")


def _content(api_key: str, timeout: float, retrieve_id: str) -> str:
    data = request("GET", "/retrieve", api_key, timeout, params={"retrieve_id": retrieve_id, "formats": "markdown"})
    return data.get("markdown_content") or ""


def collect(kind: str, job_id: str, api_key: str, timeout: float) -> list[Document]:
    """Every page of a completed job, with its markdown, as Documents."""
    _, listing_path, key, extra = _paths(kind, job_id)
    documents: list[Document] = []
    cursor: Any = None
    while True:
        params = {**extra, "limit": PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
        listing = request("GET", listing_path, api_key, timeout, params=params)
        rows = listing.get(key) or []
        for row in rows:
            if not row.get("retrieve_id"):
                continue
            try:
                documents.append(_document(row, _content(api_key, timeout, row["retrieve_id"]), kind, job_id))
            except OlostepError as exc:
                logger.warning("Skipping {url}: {error}", url=row.get("url"), error=str(exc))
        cursor = listing.get("cursor")
        if not cursor or len(rows) < PAGE_SIZE:
            return documents


async def acollect(kind: str, job_id: str, api_key: str, timeout: float) -> list[Document]:
    """Async version of :func:`collect`, downloading page content in parallel."""
    _, listing_path, key, extra = _paths(kind, job_id)
    semaphore = asyncio.Semaphore(CONTENT_CONCURRENCY)

    async def one(row: dict[str, Any]) -> Document | None:
        async with semaphore:
            try:
                data = await arequest(
                    "GET",
                    "/retrieve",
                    api_key,
                    timeout,
                    params={"retrieve_id": row["retrieve_id"], "formats": "markdown"},
                )
            except OlostepError as exc:
                logger.warning("Skipping {url}: {error}", url=row.get("url"), error=str(exc))
                return None
        return _document(row, data.get("markdown_content") or "", kind, job_id)

    documents: list[Document] = []
    cursor: Any = None
    while True:
        params = {**extra, "limit": PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
        listing = await arequest("GET", listing_path, api_key, timeout, params=params)
        rows = [row for row in listing.get(key) or [] if row.get("retrieve_id")]
        documents += [doc for doc in await asyncio.gather(*(one(row) for row in rows)) if doc is not None]
        cursor = listing.get("cursor")
        if not cursor or len(listing.get(key) or []) < PAGE_SIZE:
            return documents
