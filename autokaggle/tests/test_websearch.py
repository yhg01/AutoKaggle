from __future__ import annotations

import json

import httpx
import pytest

from autokaggle import lookup, websearch

RESULTS = [{"title": "Example data", "url": "https://data.example.org/set", "snippet": "A public dataset."},
           {"title": "Not https", "url": "http://plain.example.org/", "snippet": ""}]


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-tests")


def client(content, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_results_keep_only_https_links_and_send_a_bounded_request(openrouter):
    seen = []
    result = websearch.search("  public   dataset ", model="test-model", client=client(json.dumps(RESULTS), seen))
    assert result["query"] == "public dataset"
    assert [item["url"] for item in result["results"]] == ["https://data.example.org/set"]
    assert seen[0]["plugins"] == [{"id": "web", "max_results": websearch.MAX_RESULTS}]
    assert seen[0]["model"] == "test-model"


def test_markdown_links_are_a_fallback(openrouter):
    result = websearch.search("q", model="m", client=client("See [Data page](https://data.example.org/page) for details."))
    assert result["results"] == [{"title": "Data page", "url": "https://data.example.org/page", "snippet": ""}]


@pytest.mark.parametrize("query", ["", "   ", "x" * (websearch.MAX_QUERY_CHARS + 1)])
def test_query_length_is_bounded(openrouter, query):
    with pytest.raises(ValueError):
        websearch.search(query, model="m", client=client("[]"))


def test_a_failed_request_reports_a_fixed_message(openrouter):
    failing = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500, text="secret provider detail")))
    with pytest.raises(ValueError, match="The web search failed"):
        websearch.search("q", model="m", client=failing)


def test_search_is_offered_only_through_openrouter(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.org/v1")
    assert "web_search" not in [tool["name"] for tool in lookup.tools()]
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    assert "web_search" in [tool["name"] for tool in lookup.tools()]
