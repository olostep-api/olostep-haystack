# SPDX-License-Identifier: Apache-2.0
import asyncio
from typing import Any, Literal

from haystack import component, default_from_dict, default_to_dict, logging
from haystack.dataclasses import Document
from haystack.utils import Secret, deserialize_secrets_inplace

from ._client import OlostepError, arequest, page_title, request, resolve_key

logger = logging.getLogger(__name__)

OutputFormat = Literal["markdown", "text", "html"]


@component
class OlostepScraper:
    """
    Fetches web pages with Olostep, after rendering JavaScript, and returns them as Documents.

    Each Document holds the page as markdown (or text or HTML), with `url`, `title` and
    `status_code` in its meta. Pages that fail are skipped with a warning, unless
    `raise_on_failure=True`.

    Usage:
    ```python
    from haystack_integrations.components.websearch.olostep import OlostepScraper

    scraper = OlostepScraper()
    documents = scraper.run(urls=["https://haystack.deepset.ai/overview/intro"])["documents"]
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("OLOSTEP_API_KEY"),
        output_format: OutputFormat = "markdown",
        country: str | None = None,
        wait_before_scraping: int | None = None,
        raise_on_failure: bool = False,
        max_concurrency: int = 5,
        timeout: float = 120.0,
    ):
        """
        :param api_key: Olostep API key. Defaults to the `OLOSTEP_API_KEY` environment variable.
        :param output_format: "markdown", "text" or "html".
        :param country: Optional country code to scrape from, such as "US".
        :param wait_before_scraping: Optional milliseconds to wait for the page before scraping.
        :param raise_on_failure: Raise on the first failed page instead of skipping it.
        :param max_concurrency: Pages fetched in parallel by `run_async`.
        :param timeout: Seconds to wait for each page.
        """
        if output_format not in ("markdown", "text", "html"):
            raise ValueError("output_format must be markdown, text or html")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.api_key = api_key
        self.output_format = output_format
        self.country = country
        self.wait_before_scraping = wait_before_scraping
        self.raise_on_failure = raise_on_failure
        self.max_concurrency = max_concurrency
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(
            self,
            api_key=self.api_key.to_dict(),
            output_format=self.output_format,
            country=self.country,
            wait_before_scraping=self.wait_before_scraping,
            raise_on_failure=self.raise_on_failure,
            max_concurrency=self.max_concurrency,
            timeout=self.timeout,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OlostepScraper":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    def _payload(self, url: str) -> dict[str, Any]:
        formats = [self.output_format] if self.output_format == "html" else [self.output_format, "html"]
        payload: dict[str, Any] = {"url_to_scrape": url, "formats": formats}
        if self.country:
            payload["country"] = self.country
        if self.wait_before_scraping is not None:
            payload["wait_before_scraping"] = self.wait_before_scraping
        return payload

    def _document(self, url: str, data: dict[str, Any]) -> Document:
        result = data.get("result") or {}
        content = result.get(f"{self.output_format}_content") or ""
        status = (result.get("page_metadata") or {}).get("status_code")
        if not content:
            raise OlostepError(
                f"Olostep returned no content for {url}" + (f" (page status {status})" if status else "")
            )
        meta = {"url": url, "title": page_title(result.get("html_content")), "source": "olostep"}
        if status is not None:
            meta["status_code"] = status
        return Document(content=content, meta=meta)

    def _failed(self, url: str, error: Exception) -> None:
        if self.raise_on_failure:
            raise error
        logger.warning("Skipping {url}: {error}", url=url, error=str(error))

    @component.output_types(documents=list[Document])
    def run(self, urls: list[str]) -> dict[str, list[Document]]:
        """
        Fetch the pages.

        :param urls: The page URLs.
        :returns: A dictionary with `documents`, one per page fetched.
        """
        documents = []
        for url in urls:
            try:
                data = request("POST", "/scrapes", resolve_key(self.api_key), self.timeout, json=self._payload(url))
                documents.append(self._document(url, data))
            except OlostepError as exc:
                self._failed(url, exc)
        return {"documents": documents}

    @component.output_types(documents=list[Document])
    async def run_async(self, urls: list[str]) -> dict[str, list[Document]]:
        """Async version of :meth:`run`, fetching up to `max_concurrency` pages at a time."""
        semaphore = asyncio.Semaphore(self.max_concurrency)
        key = resolve_key(self.api_key)

        async def one(url: str) -> Document | None:
            async with semaphore:
                try:
                    data = await arequest("POST", "/scrapes", key, self.timeout, json=self._payload(url))
                    return self._document(url, data)
                except OlostepError as exc:
                    self._failed(url, exc)
                    return None

        results = await asyncio.gather(*(one(url) for url in urls))
        return {"documents": [doc for doc in results if doc is not None]}
