# SPDX-License-Identifier: Apache-2.0
from typing import Any

from haystack import component, default_from_dict, default_to_dict
from haystack.dataclasses import Document
from haystack.utils import Secret, deserialize_secrets_inplace

from . import _jobs
from ._client import OlostepError, arequest, clean, request, resolve_key


@component
class OlostepCrawler:
    """
    Crawls a website with Olostep: follows links from a start URL and returns each page as a markdown Document.

    Waits for the crawl to finish (up to `wait_timeout` seconds), then returns every page it found.

    Usage:
    ```python
    from haystack_integrations.components.websearch.olostep import OlostepCrawler

    crawler = OlostepCrawler(max_pages=25, include_url_patterns=["/docs/**"])
    documents = crawler.run(url="https://docs.haystack.deepset.ai/docs/intro")["documents"]
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("OLOSTEP_API_KEY"),
        max_pages: int = 10,
        max_depth: int | None = None,
        include_url_patterns: list[str] | None = None,
        exclude_url_patterns: list[str] | None = None,
        search_query: str | None = None,
        wait_timeout: float = 600.0,
        poll_interval: float = 5.0,
        timeout: float = 60.0,
    ):
        """
        :param api_key: Olostep API key. Defaults to the `OLOSTEP_API_KEY` environment variable.
        :param max_pages: Maximum pages to crawl.
        :param max_depth: Maximum link depth from the start URL.
        :param include_url_patterns: Glob patterns of URLs to follow, such as `/docs/**`.
        :param exclude_url_patterns: Glob patterns of URLs to skip.
        :param search_query: Prioritise pages relevant to this query.
        :param wait_timeout: Seconds to wait for the crawl to finish.
        :param poll_interval: Seconds between status checks.
        :param timeout: Seconds to wait for each API call.
        """
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self.api_key = api_key
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.include_url_patterns = include_url_patterns
        self.exclude_url_patterns = exclude_url_patterns
        self.search_query = search_query
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(
            self,
            api_key=self.api_key.to_dict(),
            max_pages=self.max_pages,
            max_depth=self.max_depth,
            include_url_patterns=self.include_url_patterns,
            exclude_url_patterns=self.exclude_url_patterns,
            search_query=self.search_query,
            wait_timeout=self.wait_timeout,
            poll_interval=self.poll_interval,
            timeout=self.timeout,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OlostepCrawler":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    def _payload(self, url: str) -> dict[str, Any]:
        if not url or not url.strip():
            raise ValueError("url must not be empty")
        return clean(
            {
                "start_url": url.strip(),
                "max_pages": self.max_pages,
                "max_depth": self.max_depth,
                "include_urls": self.include_url_patterns,
                "exclude_urls": self.exclude_url_patterns,
                "search_query": self.search_query,
            }
        )

    @component.output_types(documents=list[Document])
    def run(self, url: str) -> dict[str, list[Document]]:
        """
        Crawl the site.

        :param url: The URL to start from.
        :returns: A dictionary with `documents`, one per crawled page.
        :raises OlostepError: If the crawl fails or doesn't finish within `wait_timeout`.
        """
        key = resolve_key(self.api_key)
        started = request("POST", "/crawls", key, self.timeout, json=self._payload(url))
        crawl_id = started.get("id")
        if not crawl_id:
            raise OlostepError("Olostep did not return a crawl id")
        _jobs.wait("crawl", crawl_id, started.get("status"), key, self.timeout, self.wait_timeout, self.poll_interval)
        return {"documents": _jobs.collect("crawl", crawl_id, key, self.timeout)}

    @component.output_types(documents=list[Document])
    async def run_async(self, url: str) -> dict[str, list[Document]]:
        """Async version of :meth:`run`."""
        key = resolve_key(self.api_key)
        started = await arequest("POST", "/crawls", key, self.timeout, json=self._payload(url))
        crawl_id = started.get("id")
        if not crawl_id:
            raise OlostepError("Olostep did not return a crawl id")
        await _jobs.await_job(
            "crawl", crawl_id, started.get("status"), key, self.timeout, self.wait_timeout, self.poll_interval
        )
        return {"documents": await _jobs.acollect("crawl", crawl_id, key, self.timeout)}
