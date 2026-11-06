"""Web search for the interviewer: titles, links and short snippets, as untrusted text.

The search runs through the configured OpenRouter endpoint and its web plugin.
Only result links are returned; pages are read separately with fetch_url, and
only links that a search returned or the researcher sent can be opened.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

import httpx

MAX_QUERY_CHARS = 200
MAX_RESULTS = 5
INSTRUCTION = ("Search the web for the query below. Reply with only a JSON array of the results you found, each "
               '{"title": "...", "url": "https://...", "snippet": "one or two sentences from the page"}, '
               "and nothing else. Do not answer the query yourself.\n\nQuery: ")
LINK = re.compile(r"\[([^\]]{1,300})\]\((https://[^\s)]+)\)")


def available():
    return "openrouter.ai" in os.getenv("OPENAI_BASE_URL", "") and bool(os.getenv("OPENAI_API_KEY"))


def _results(text):
    """Parse the JSON list of results, or fall back to markdown links."""
    try:
        start, end = text.index("["), text.rindex("]") + 1
        parsed = json.loads(text[start:end])
        items = [{"title": str(item.get("title", ""))[:300], "url": str(item.get("url", "")), "snippet": str(item.get("snippet", ""))[:400]}
                 for item in parsed if isinstance(item, dict)]
    except (ValueError, json.JSONDecodeError):
        items = [{"title": title, "url": url, "snippet": ""} for title, url in LINK.findall(text)]
    clean = [item for item in items if urlparse(item["url"]).scheme == "https" and urlparse(item["url"]).hostname]
    return list({item["url"]: item for item in clean}.values())[:MAX_RESULTS]


def search(query, *, model, client=None):
    """Return {"query", "results": [{title, url, snippet}]} or raise ValueError."""
    query = " ".join(str(query).split())
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"A search query needs 1 to {MAX_QUERY_CHARS} characters.")
    if not available():
        raise ValueError("Web search is not available with the configured model provider.")
    body = {"model": model, "plugins": [{"id": "web", "max_results": MAX_RESULTS}],
            "messages": [{"role": "user", "content": INSTRUCTION + query}]}
    owned = client is None
    client = client or httpx.Client(timeout=90)
    try:
        response = client.post(os.environ["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions",
                               headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]}, json=body)
        response.raise_for_status()
        text = response.json()["choices"][0]["message"].get("content") or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        raise ValueError("The web search failed.") from None
    finally:
        if owned:
            client.close()
    return {"query": query, "results": _results(text)}
