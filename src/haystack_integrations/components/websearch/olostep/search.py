# SPDX-License-Identifier: Apache-2.0
from typing import Any

from haystack import component, default_from_dict, default_to_dict
from haystack.dataclasses import Document
from haystack.utils import Secret, deserialize_secrets_inplace

from ._client import arequest, clean, request, resolve_key

MAX_RESULTS = 25  # /v1/searches returns 1-25 results


@component
class OlostepWebSearch:
    """
    Searches the live web with Olostep and returns the results as Documents.

    Each Document holds the result's description, or the full page as markdown when
    `scrape_results=True`, with `title`, `url` and `position` in its meta.

    Usage:
    ```python
    from haystack_integrations.components.websearch.olostep import OlostepWebSearch

    search = OlostepWebSearch(top_k=5)
    result = search.run(query="What is Haystack by deepset?")
    documents, links = result["documents"], result["links"]
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("OLOSTEP_API_KEY"),
        top_k: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        scrape_results: bool = False,
        timeout: float = 60.0,
    ):
        """
        :param api_key: Olostep API key. Defaults to the `OLOSTEP_API_KEY` environment variable.
        :param top_k: Number of results, 1 to 25.
        :param include_domains: Only return results from these domains.
        :param exclude_domains: Never return results from these domains.
        :param scrape_results: Also fetch each result page and use its markdown as the Document content
            (uses additional credits per page).
        :param timeout: Seconds to wait for the API.
        """
        if not 1 <= top_k <= MAX_RESULTS:
            raise ValueError(f"top_k must be between 1 and {MAX_RESULTS}")
        self.api_key = api_key
        self.top_k = top_k
        self.include_domains = include_domains
        self.exclude_domains = exclude_domains
        self.scrape_results = scrape_results
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(
            self,
            api_key=self.api_key.to_dict(),
            top_k=self.top_k,
            include_domains=self.include_domains,
            exclude_domains=self.exclude_domains,
            scrape_results=self.scrape_results,
            timeout=self.timeout,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OlostepWebSearch":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    def _payload(self, query: str) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        payload = {
            "query": query.strip(),
            "limit": self.top_k,
            "include_domains": self.include_domains,
            "exclude_domains": self.exclude_domains,
        }
        if self.scrape_results:
            payload["scrape_options"] = {"formats": ["markdown"]}
        return clean(payload)

    def _output(self, data: dict[str, Any]) -> dict[str, Any]:
        documents: list[Document] = []
        for link in (data.get("result") or {}).get("links") or []:
            url = link.get("url")
            if not url:
                continue
            content = (link.get("markdown_content") if self.scrape_results else None) or link.get("description") or ""
            meta = {"title": link.get("title") or "", "url": url, "position": len(documents) + 1, "source": "olostep"}
            if link.get("published_at"):
                meta["published_at"] = link["published_at"]
            documents.append(Document(content=content, meta=meta))
        return {"documents": documents, "links": [doc.meta["url"] for doc in documents]}

    @component.output_types(documents=list[Document], links=list[str])
    def run(self, query: str) -> dict[str, Any]:
        """
        Search the web.

        :param query: What to search for.
        :returns: A dictionary with `documents` (one per result) and `links` (their URLs).
        """
        return self._output(
            request("POST", "/searches", resolve_key(self.api_key), self.timeout, json=self._payload(query))
        )

    @component.output_types(documents=list[Document], links=list[str])
    async def run_async(self, query: str) -> dict[str, Any]:
        """Async version of :meth:`run`."""
        data = await arequest("POST", "/searches", resolve_key(self.api_key), self.timeout, json=self._payload(query))
        return self._output(data)
