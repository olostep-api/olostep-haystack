# SPDX-License-Identifier: Apache-2.0
from typing import Any

from haystack import component, default_from_dict, default_to_dict
from haystack.utils import Secret, deserialize_secrets_inplace

from ._client import arequest, clean, request, resolve_key


@component
class OlostepMapper:
    """
    Lists the URLs of a website with Olostep, without fetching them.

    Rank the URLs by relevance with `search_query`, keep the best with `top_n`, or filter
    them with glob patterns such as `/docs/**`. Connect `links` to `OlostepScraper.urls`
    to fetch the pages.

    Usage:
    ```python
    from haystack_integrations.components.websearch.olostep import OlostepMapper

    mapper = OlostepMapper(top_n=20, include_url_patterns=["/docs/**"])
    links = mapper.run(url="https://docs.haystack.deepset.ai", search_query="retrievers")["links"]
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("OLOSTEP_API_KEY"),
        top_n: int | None = None,
        include_url_patterns: list[str] | None = None,
        exclude_url_patterns: list[str] | None = None,
        include_subdomain: bool | None = None,
        timeout: float = 180.0,
    ):
        """
        :param api_key: Olostep API key. Defaults to the `OLOSTEP_API_KEY` environment variable.
        :param top_n: Keep only the N most relevant URLs.
        :param include_url_patterns: Glob patterns of URLs to keep, such as `/blog/**`.
        :param exclude_url_patterns: Glob patterns of URLs to drop.
        :param include_subdomain: Also include URLs on subdomains.
        :param timeout: Seconds to wait for the map.
        """
        self.api_key = api_key
        self.top_n = top_n
        self.include_url_patterns = include_url_patterns
        self.exclude_url_patterns = exclude_url_patterns
        self.include_subdomain = include_subdomain
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(
            self,
            api_key=self.api_key.to_dict(),
            top_n=self.top_n,
            include_url_patterns=self.include_url_patterns,
            exclude_url_patterns=self.exclude_url_patterns,
            include_subdomain=self.include_subdomain,
            timeout=self.timeout,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OlostepMapper":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    def _payload(self, url: str, search_query: str | None) -> dict[str, Any]:
        if not url or not url.strip():
            raise ValueError("url must not be empty")
        return clean(
            {
                "url": url.strip(),
                "search_query": search_query,
                "top_n": self.top_n,
                "include_urls": self.include_url_patterns,
                "exclude_urls": self.exclude_url_patterns,
                "include_subdomain": self.include_subdomain,
            }
        )

    @component.output_types(links=list[str])
    def run(self, url: str, search_query: str | None = None) -> dict[str, list[str]]:
        """
        List the site's URLs.

        :param url: The website, such as `https://docs.example.com`.
        :param search_query: Optional query to rank the URLs by relevance.
        :returns: A dictionary with `links`.
        """
        data = request("POST", "/maps", resolve_key(self.api_key), self.timeout, json=self._payload(url, search_query))
        return {"links": list(data.get("urls") or [])}

    @component.output_types(links=list[str])
    async def run_async(self, url: str, search_query: str | None = None) -> dict[str, list[str]]:
        """Async version of :meth:`run`."""
        payload = self._payload(url, search_query)
        data = await arequest("POST", "/maps", resolve_key(self.api_key), self.timeout, json=payload)
        return {"links": list(data.get("urls") or [])}
