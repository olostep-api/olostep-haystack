# olostep-haystack

[![PyPI](https://img.shields.io/pypi/v/olostep-haystack.svg)](https://pypi.org/project/olostep-haystack/)

[Haystack](https://haystack.deepset.ai) components for [Olostep](https://www.olostep.com): live web search, scraping, crawling, answers with sources, and batch extraction of up to 100k URLs per batch, all returning Haystack `Document`s you can index, rank or pass to an LLM.

## Why Olostep

Olostep is web data infrastructure for AI agents and enterprise AI workflows. Its APIs provide live web search, scraping and crawling to extract, clean and structure data from the web.

From a handful of URLs to hundreds of millions of pages, Olostep gives developers, AI companies and enterprises reliable, cost-effective access to clean, structured web data at scale. It's built for performance and high concurrency: up to 100k URLs in a single batch, and 1M with 10 batches in parallel. Pages are rendered with JavaScript, so single-page apps and dynamic sites come back complete.

New accounts get **500 free credits**, no credit card required.

## Installation

```bash
pip install olostep-haystack
```

Get an API key at [olostep.com](https://www.olostep.com/dashboard) and set it as `OLOSTEP_API_KEY`. Works with Haystack 2.12 and later, including 3.x, on Python 3.10+.

## Components

| Component | Input | Output |
|---|---|---|
| `OlostepWebSearch` | `query` | `documents` (one per result) and `links` |
| `OlostepScraper` | `urls` | `documents` (each page as markdown, text or HTML) |
| `OlostepAnswer` | `query` | `answer` (text, or JSON in your shape) and `links` (sources) |
| `OlostepMapper` | `url`, optional `search_query` | `links` (the site's URLs) |
| `OlostepCrawler` | `url` | `documents` (every crawled page as markdown) |
| `OlostepBatchScraper` | `urls` (up to 100,000) | `documents` (every page as markdown) |

Every component has `run` and `run_async`, and saves and loads with the pipeline. The API key is stored as a reference to `OLOSTEP_API_KEY`, never as its value.

## Usage

### Search the web

```python
from haystack_integrations.components.websearch.olostep import OlostepWebSearch

search = OlostepWebSearch(top_k=5)
result = search.run(query="What is retrieval-augmented generation?")

for doc in result["documents"]:
    print(doc.meta["title"], doc.meta["url"])
```

Set `scrape_results=True` to get each result page's full markdown as the Document content, and `include_domains` / `exclude_domains` to control the sources.

### Scrape pages

```python
from haystack_integrations.components.websearch.olostep import OlostepScraper

scraper = OlostepScraper()
documents = scraper.run(urls=["https://haystack.deepset.ai/overview/intro"])["documents"]
print(documents[0].meta["title"], len(documents[0].content))
```

### Answer a question, with sources

```python
from haystack_integrations.components.websearch.olostep import OlostepAnswer

answer = OlostepAnswer(json_format={"company": "", "founded": ""})
result = answer.run(query="When was deepset founded?")
print(result["answer"], result["links"])
```

### Index a docs site: map, then scrape

```python
from haystack import Pipeline
from haystack.components.writers import DocumentWriter
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack_integrations.components.websearch.olostep import OlostepMapper, OlostepScraper

store = InMemoryDocumentStore()
pipeline = Pipeline()
pipeline.add_component("mapper", OlostepMapper(top_n=20, include_url_patterns=["/docs/**"]))
pipeline.add_component("scraper", OlostepScraper())
pipeline.add_component("writer", DocumentWriter(document_store=store))
pipeline.connect("mapper.links", "scraper.urls")
pipeline.connect("scraper.documents", "writer.documents")

pipeline.run({"mapper": {"url": "https://docs.haystack.deepset.ai", "search_query": "retrievers"}})
print(store.count_documents())
```

### Crawl a site or batch-scrape many URLs

```python
from haystack_integrations.components.websearch.olostep import OlostepBatchScraper, OlostepCrawler

docs = OlostepCrawler(max_pages=50, include_url_patterns=["/blog/**"]).run(url="https://example.com/blog")["documents"]

# Up to 100,000 URLs per batch. Waits for the batch to finish (up to wait_timeout seconds).
docs = OlostepBatchScraper().run(urls=product_urls)["documents"]
```

For a handful of URLs, `OlostepScraper` is faster than a batch.

## Errors

API errors raise `OlostepError` with a readable message (a bad key, no credits, a failed crawl). Rate limits, gateway errors and network failures are retried twice. `OlostepScraper` skips pages it couldn't fetch, with a warning; set `raise_on_failure=True` to stop instead.

## Development

```bash
pip install -e . pytest ruff mypy
pytest
ruff check src tests && ruff format --check src tests && mypy src
```

The tests mock the Olostep API, so they don't need a key.

## Links

- [Olostep](https://www.olostep.com)
- [Olostep docs](https://docs.olostep.com)
- [Haystack](https://haystack.deepset.ai)

## License

Apache-2.0
