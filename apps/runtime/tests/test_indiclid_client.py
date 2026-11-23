"""IndicLidClient: batching, local filtering and failure handling."""

from __future__ import annotations

import json

import httpx
import pytest

from apps.runtime.services.language_switch.lid.indiclid import (
    IndicLidClient,
    latin_fraction,
    script_of,
)


def _result(lang: str, label: str) -> dict:
    ranking = [
        {"lang": code, "label": f"{code}_x", "score": 1.0 if code == lang else 0.0}
        for code in ("kn", "hi", "mr", "ta", "te")
    ]
    return {
        "ranking": ranking,
        "other_languages_mass": 0.0,
        "top_overall_label": label,
        "top_overall_score": 1.0,
    }


def _client(handler) -> IndicLidClient:
    client = IndicLidClient("http://indiclid.test")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def test_script_detection():
    assert script_of("ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ") == "Knda"
    assert script_of("नमस्कार निवु हेगिद्दीरी") == "Deva"
    assert script_of("வணக்கம் நீங்கள்") == "Taml"
    assert script_of("నమస్కారం మీరు") == "Telu"
    assert script_of("hello there") == "Latn"
    assert script_of("1234 ?!") == "other"
    assert latin_fraction("नमस्ते hello") > 0.5 - 1e-9


@pytest.mark.asyncio
async def test_batches_texts_and_aligns_results():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200, json={"results": [_result("kn", "kan_Knda"), _result("mr", "mar_Deva")]}
        )

    client = _client(handler)
    out = await client.score(["ನಮಸ್ಕಾರ ನೀವು", "", "  ", "नमस्कार तुम्ही कसे आहात", "hello world"])

    assert len(seen) == 1 and len(seen[0]["texts"]) == 2
    assert [e is None for e in out] == [False, True, True, False, True]
    assert out[0].scores["kn"] == 1.0 and out[0].script == "Knda"
    assert out[3].scores["mr"] == 1.0 and out[3].top_label == "mar_Deva"


@pytest.mark.asyncio
async def test_no_call_when_nothing_to_score():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call the service")

    out = await _client(handler).score(["", "hello world"])
    assert out == [None, None]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"detail": "Romanized"}),
        httpx.Response(503),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"results": []}),
        httpx.Response(200, json={"nope": 1}),
    ],
)
async def test_failures_return_all_none(response):
    out = await _client(lambda request: response).score(["ನಮಸ್ಕಾರ ನೀವು"])
    assert out == [None]


@pytest.mark.asyncio
async def test_timeout_returns_all_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    out = await _client(handler).score(["ನಮಸ್ಕಾರ ನೀವು", "नमस्कार तुम्ही"])
    assert out == [None, None]
