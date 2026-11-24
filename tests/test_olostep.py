# SPDX-License-Identifier: Apache-2.0
"""Unit tests with the Olostep API mocked by httpx.MockTransport."""

import asyncio
import copy
import json

import httpx
import pytest
from haystack import Pipeline
from haystack.utils import Secret

from haystack_integrations.components.websearch.olostep import (
    OlostepAnswer,
    OlostepBatchScraper,
    OlostepCrawler,
    OlostepError,
    OlostepMapper,
    OlostepScraper,
    OlostepWebSearch,
    _client,
    _jobs,
)

KEY = Secret.from_token("test-key")
REAL_CLIENT, REAL_ASYNC_CLIENT = httpx.Client, httpx.AsyncClient


class FakeApi:
    """Answers (method, path) with a JSON body, a callable, or a list of responses in turn."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def on(self, method, path, body, status=200):
        self.routes[(method, path)] = (body, status)

    def __call__(self, request):
        self.calls.append(request)
        route = self.routes.get((request.method, request.url.path.removeprefix("/v1")))
        if route is None:
            return httpx.Response(404, json={"detail": "no route"})
        body, status = route
        if callable(body):
            return body(request)
        if isinstance(body, list):
            body, status = body.pop(0) if len(body) > 1 else body[0]
        return httpx.Response(status, json=body)

    def body(self, index=-1):
        return json.loads(self.calls[index].content)

    def paths(self):
        return [c.url.path.removeprefix("/v1") for c in self.calls]


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: REAL_CLIENT(transport=transport, **kw))
    monkeypatch.setattr(_client.httpx, "AsyncClient", lambda **kw: REAL_ASYNC_CLIENT(transport=transport, **kw))
    monkeypatch.setattr(_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(_jobs.time, "sleep", lambda s: None)

    async def no_wait(s):
        return None

    monkeypatch.setattr(_client.asyncio, "sleep", no_wait)
    monkeypatch.setattr(_jobs.asyncio, "sleep", no_wait)
    return fake


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- serialization
@pytest.mark.parametrize(
    "component",
    [
        OlostepWebSearch(top_k=3, include_domains=["a.com"]),
        OlostepScraper(output_format="text", country="US"),
        OlostepAnswer(json_format={"name": ""}),
        OlostepMapper(top_n=5, include_url_patterns=["/docs/**"]),
        OlostepCrawler(max_pages=20),
        OlostepBatchScraper(country="DE"),
    ],
)
def test_to_dict_from_dict_keeps_settings_and_hides_key(component, monkeypatch):
    monkeypatch.setenv("OLOSTEP_API_KEY", "secret-value")
    data = component.to_dict()
    assert data["init_parameters"]["api_key"] == {"type": "env_var", "env_vars": ["OLOSTEP_API_KEY"], "strict": True}
    assert "secret-value" not in json.dumps(data)
    assert type(component).from_dict(copy.deepcopy(data)).to_dict() == data


def test_invalid_settings():
    with pytest.raises(ValueError):
        OlostepWebSearch(top_k=26)
    with pytest.raises(ValueError):
        OlostepScraper(output_format="pdf")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OlostepCrawler(max_pages=0)


# ---------------------------------------------------------------- search
def test_web_search(api):
    links = [
        {"url": "https://a.example", "title": "A", "description": "first", "published_at": "2026-01-01"},
        {"url": "", "title": "no url"},
        {"url": "https://b.example", "title": "B", "description": None},
    ]
    api.on("POST", "/searches", {"result": {"links": links}})
    out = OlostepWebSearch(api_key=KEY, top_k=5, include_domains=["a.example"]).run("haystack")
    assert out["links"] == ["https://a.example", "https://b.example"]
    first = out["documents"][0]
    assert first.content == "first"
    assert first.meta == {
        "title": "A",
        "url": "https://a.example",
        "position": 1,
        "source": "olostep",
        "published_at": "2026-01-01",
    }
    assert api.body() == {"query": "haystack", "limit": 5, "include_domains": ["a.example"]}
    assert api.calls[-1].headers["Authorization"] == "Bearer test-key"


def test_web_search_with_page_content(api):
    links = [{"url": "https://a.example", "title": "A", "description": "d", "markdown_content": "# Page"}]
    api.on("POST", "/searches", {"result": {"links": links}})
    out = OlostepWebSearch(api_key=KEY, scrape_results=True).run("q")
    assert out["documents"][0].content == "# Page"
    assert api.body()["scrape_options"] == {"formats": ["markdown"]}


def test_web_search_rejects_empty_query(api):
    with pytest.raises(ValueError):
        OlostepWebSearch(api_key=KEY).run("  ")
    assert api.calls == []


# ---------------------------------------------------------------- scraper
def test_scraper(api):
    def scrape(request):
        url = json.loads(request.content)["url_to_scrape"]
        if "bad" in url:
            return httpx.Response(500, json={"detail": "upstream"})
        result = {"markdown_content": f"# {url}", "html_content": "<title> Example &amp; Co </title>"}
        result["page_metadata"] = {"status_code": 200}
        return httpx.Response(200, json={"result": result})

    api.on("POST", "/scrapes", scrape)
    out = OlostepScraper(api_key=KEY).run(["https://ok.example", "https://bad.example"])
    assert len(out["documents"]) == 1
    doc = out["documents"][0]
    assert doc.content == "# https://ok.example"
    assert doc.meta == {"url": "https://ok.example", "title": "Example & Co", "source": "olostep", "status_code": 200}
    assert api.body(0) == {"url_to_scrape": "https://ok.example", "formats": ["markdown", "html"]}


def test_scraper_raise_on_failure(api):
    api.on("POST", "/scrapes", {"result": {"markdown_content": ""}})
    with pytest.raises(OlostepError, match="no content"):
        OlostepScraper(api_key=KEY, raise_on_failure=True).run(["https://empty.example"])


def test_scraper_async(api):
    api.on("POST", "/scrapes", {"result": {"text_content": "plain", "html_content": ""}})
    out = run(OlostepScraper(api_key=KEY, output_format="text").run_async(["https://a.example", "https://b.example"]))
    assert [d.content for d in out["documents"]] == ["plain", "plain"]


# ---------------------------------------------------------------- answer / mapper
def test_answer_structured(api):
    api.on("POST", "/answers", {"result": {"json_content": '{"year": "1889"}', "sources": ["https://s.example"]}})
    out = OlostepAnswer(api_key=KEY, json_format={"year": ""}).run("When was the Eiffel Tower completed?")
    assert out == {"answer": {"year": "1889"}, "links": ["https://s.example"]}
    assert api.body()["json_format"] == {"year": ""}


def test_answer_async_text(api):
    api.on("POST", "/answers", {"result": {"json_content": "Tokyo", "sources": []}})
    assert run(OlostepAnswer(api_key=KEY).run_async("Capital of Japan?")) == {"answer": "Tokyo", "links": []}


def test_mapper_feeds_scraper_in_a_pipeline(api):
    api.on("POST", "/maps", {"urls": ["https://d.example/a", "https://d.example/b"]})
    api.on("POST", "/scrapes", {"result": {"markdown_content": "# Doc", "html_content": ""}})
    pipeline = Pipeline()
    pipeline.add_component("mapper", OlostepMapper(api_key=KEY, top_n=2, include_url_patterns=["/docs/**"]))
    pipeline.add_component("scraper", OlostepScraper(api_key=KEY))
    pipeline.connect("mapper.links", "scraper.urls")
    out = pipeline.run({"mapper": {"url": "https://d.example", "search_query": "api"}})
    assert len(out["scraper"]["documents"]) == 2
    assert api.body(0) == {"url": "https://d.example", "search_query": "api", "top_n": 2, "include_urls": ["/docs/**"]}


# ---------------------------------------------------------------- crawler / batch
def _crawl(api, statuses):
    api.on("POST", "/crawls", {"id": "crawl_1", "status": "in_progress"})
    api.on("GET", "/crawls/crawl_1", [({"status": s}, 200) for s in statuses])
    pages = [{"url": "https://e.example/", "retrieve_id": "r1"}, {"url": "https://e.example/x"}]
    api.on("GET", "/crawls/crawl_1/pages", {"pages": pages, "cursor": None})
    api.on("GET", "/retrieve", {"markdown_content": "# Page"})


def test_crawler(api):
    _crawl(api, ["in_progress", "completed"])
    docs = OlostepCrawler(api_key=KEY, max_pages=2, poll_interval=0.01).run("https://e.example")["documents"]
    assert [(d.content, d.meta["url"], d.meta["crawl_id"]) for d in docs] == [
        ("# Page", "https://e.example/", "crawl_1")
    ]
    assert api.body(0) == {"start_url": "https://e.example", "max_pages": 2}


def test_crawler_async(api):
    _crawl(api, ["completed"])
    assert len(run(OlostepCrawler(api_key=KEY).run_async("https://e.example"))["documents"]) == 1


def test_crawler_failure_and_timeout(api):
    _crawl(api, ["failed"])
    with pytest.raises(OlostepError, match="failed"):
        OlostepCrawler(api_key=KEY).run("https://e.example")
    _crawl(api, ["in_progress"])
    with pytest.raises(OlostepError, match="still in_progress"):
        OlostepCrawler(api_key=KEY, wait_timeout=0).run("https://e.example")


def test_batch_scraper_pages_through_items(api, monkeypatch):
    monkeypatch.setattr(_jobs, "PAGE_SIZE", 1)
    api.on("POST", "/batches", {"id": "batch_1", "status": "in_progress"})
    api.on("GET", "/batches/batch_1", {"status": "completed"})
    first = {"items": [{"url": "https://a.example", "custom_id": "0", "retrieve_id": "r0"}], "cursor": 1}
    last = {"items": [], "cursor": None}
    api.on("GET", "/batches/batch_1/items", [(first, 200), (last, 200)])
    api.on("GET", "/retrieve", {"markdown_content": "# A"})
    docs = OlostepBatchScraper(api_key=KEY, country="US").run([" https://a.example ", ""])["documents"]
    assert [(d.meta["custom_id"], d.content) for d in docs] == [("0", "# A")]
    assert api.body(0) == {"items": [{"custom_id": "0", "url": "https://a.example"}], "country": "US"}
    item_calls = [c for c in api.calls if c.url.path.endswith("/items")]
    assert item_calls[0].url.params["status"] == "completed" and item_calls[1].url.params["cursor"] == "1"


def test_batch_rejects_more_than_100k(api):
    with pytest.raises(ValueError, match="100,000"):
        OlostepBatchScraper(api_key=KEY).run(["https://a.example"] * 100_001)
    assert api.calls == []


# ---------------------------------------------------------------- errors and retries
@pytest.mark.parametrize(("status", "fragment"), [(401, "API key"), (402, "out of credits"), (500, "HTTP 500: boom")])
def test_http_errors(api, status, fragment):
    api.on("POST", "/searches", {"detail": "boom"}, status=status)
    with pytest.raises(OlostepError, match=fragment):
        OlostepWebSearch(api_key=KEY).run("q")


def test_retries_rate_limit_then_succeeds(api):
    api.on("POST", "/searches", [({"detail": "slow down"}, 429), ({"result": {"links": []}}, 200)])
    assert OlostepWebSearch(api_key=KEY).run("q")["documents"] == []
    assert api.paths().count("/searches") == 2


def test_gives_up_after_retries(api):
    api.on("POST", "/searches", {"detail": "busy"}, status=503)
    with pytest.raises(OlostepError, match="503"):
        OlostepWebSearch(api_key=KEY).run("q")
    assert api.paths().count("/searches") == _client.RETRIES + 1
