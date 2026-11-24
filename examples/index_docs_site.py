"""Index a documentation site with Olostep and Haystack: map the site, scrape the pages, store them.

Set OLOSTEP_API_KEY first (new accounts get 500 free credits at https://www.olostep.com).
"""

from haystack import Pipeline
from haystack.components.writers import DocumentWriter
from haystack.document_stores.in_memory import InMemoryDocumentStore

from haystack_integrations.components.websearch.olostep import OlostepMapper, OlostepScraper

store = InMemoryDocumentStore()
pipeline = Pipeline()
pipeline.add_component("mapper", OlostepMapper(top_n=10))
pipeline.add_component("scraper", OlostepScraper())
pipeline.add_component("writer", DocumentWriter(document_store=store))
pipeline.connect("mapper.links", "scraper.urls")
pipeline.connect("scraper.documents", "writer.documents")

if __name__ == "__main__":
    pipeline.run({"mapper": {"url": "https://docs.olostep.com", "search_query": "batch"}})
    for doc in store.filter_documents():
        print(doc.meta["title"], doc.meta["url"], len(doc.content))
