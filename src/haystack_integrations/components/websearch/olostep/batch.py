# SPDX-License-Identifier: Apache-2.0
from typing import Any

from haystack import component, default_from_dict, default_to_dict
from haystack.dataclasses import Document
from haystack.utils import Secret, deserialize_secrets_inplace

from . import _jobs
from ._client import OlostepError, arequest, request, resolve_key

MAX_BATCH_URLS = 100_000  # one batch holds up to 100k URLs


@component
class OlostepBatchScraper:
    """
    Scrapes a list of URLs in one Olostep batch job (up to 100,000 URLs per batch) and returns
    each page as a markdown Document.

    Built for indexing pipelines: it waits for the batch to finish (up to `wait_timeout`
    seconds). For a handful of URLs, `OlostepScraper` is faster.

    Usage:
    ```python
    from haystack_integrations.components.websearch.olostep import OlostepBatchScraper

    batch = OlostepBatchScraper()
    documents = batch.run(urls=urls)["documents"]  # each Document has url and custom_id in meta
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("OLOSTEP_API_KEY"),
        country: str | None = None,
        wait_timeout: float = 1800.0,
        poll_interval: float = 15.0,
        timeout: float = 120.0,
    ):
        """
        :param api_key: Olostep API key. Defaults to the `OLOSTEP_API_KEY` environment variable.
        :param country: Optional country code to scrape from, such as "US".
        :param wait_timeout: Seconds to wait for the batch to finish.
        :param poll_interval: Seconds between status checks.
        :param timeout: Seconds to wait for each API call.
        """
        self.api_key = api_key
        self.country = country
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(
            self,
            api_key=self.api_key.to_dict(),
            country=self.country,
            wait_timeout=self.wait_timeout,
            poll_interval=self.poll_interval,
            timeout=self.timeout,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OlostepBatchScraper":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    def _payload(self, urls: list[str]) -> dict[str, Any]:
        cleaned = [url.strip() for url in urls if url and url.strip()]
        if not cleaned:
            raise ValueError("urls must contain at least one URL")
        if len(cleaned) > MAX_BATCH_URLS:
            raise ValueError(f"One batch holds up to {MAX_BATCH_URLS:,} URLs; split the list into several batches")
        payload: dict[str, Any] = {"items": [{"custom_id": str(i), "url": url} for i, url in enumerate(cleaned)]}
        if self.country:
            payload["country"] = self.country
        return payload

    @component.output_types(documents=list[Document])
    def run(self, urls: list[str]) -> dict[str, list[Document]]:
        """
        Scrape the URLs in one batch.

        :param urls: The URLs to scrape, up to 100,000.
        :returns: A dictionary with `documents`, one per page scraped. `custom_id` in each Document's meta is
            the URL's position in `urls`.
        :raises OlostepError: If the batch fails or doesn't finish within `wait_timeout`.
        """
        key = resolve_key(self.api_key)
        started = request("POST", "/batches", key, self.timeout, json=self._payload(urls))
        batch_id = started.get("id")
        if not batch_id:
            raise OlostepError("Olostep did not return a batch id")
        _jobs.wait("batch", batch_id, started.get("status"), key, self.timeout, self.wait_timeout, self.poll_interval)
        return {"documents": _jobs.collect("batch", batch_id, key, self.timeout)}

    @component.output_types(documents=list[Document])
    async def run_async(self, urls: list[str]) -> dict[str, list[Document]]:
        """Async version of :meth:`run`, downloading page content in parallel."""
        key = resolve_key(self.api_key)
        started = await arequest("POST", "/batches", key, self.timeout, json=self._payload(urls))
        batch_id = started.get("id")
        if not batch_id:
            raise OlostepError("Olostep did not return a batch id")
        await _jobs.await_job(
            "batch", batch_id, started.get("status"), key, self.timeout, self.wait_timeout, self.poll_interval
        )
        return {"documents": await _jobs.acollect("batch", batch_id, key, self.timeout)}
