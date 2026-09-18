from __future__ import annotations

import base64
import io
from datetime import date
from types import SimpleNamespace

import httpx
import httpx2
import pytest
from openai import BadRequestError, RateLimitError
from PIL import Image

from merch.config import Settings
from merch.schemas import ResearchReport
from merch.services.openai_service import OpenAINonRetryableError, OpenAIService
from merch.services.printify import AmbiguousCreateError, PrintifyClient


@pytest.mark.asyncio
async def test_openai_responses_contract_uses_structured_output_and_search() -> None:
    fake_report = (await OpenAIService(Settings()).research(date.today(), "none")).value
    captured = {}

    class Responses:
        async def parse(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=fake_report,
                usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 10}),
                id="resp_fixture",
                model="gpt-6-astra",
            )

    service = OpenAIService(Settings(provider_mode="live", openai_api_key="test"))
    service.client = SimpleNamespace(responses=Responses())  # type: ignore[assignment]
    result = await service._parse("research", ResearchReport, web_search=True)
    assert result.metadata["response_id"] == "resp_fixture"
    assert captured["text_format"] is ResearchReport
    assert captured["tools"] == [{"type": "web_search"}]
    assert "temperature" not in captured


@pytest.mark.asyncio
async def test_openai_routes_research_and_caps_visual_detail() -> None:
    fake_report = (await OpenAIService(Settings()).research(date.today(), "none")).value
    captured = {}

    class Responses:
        async def parse(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=fake_report,
                usage=SimpleNamespace(
                    model_dump=lambda: {"input_tokens": 100, "output_tokens": 20}
                ),
                id="resp_fixture",
                model=kwargs["model"],
                output=[],
            )

    service = OpenAIService(Settings(provider_mode="live", openai_api_key="test"))
    service.client = SimpleNamespace(responses=Responses())  # type: ignore[assignment]
    result = await service.research(date.today(), "none")
    assert captured["model"] == "gpt-5.6-terra"
    assert captured["reasoning"] == {"effort": "medium"}
    assert result.metadata["estimated_cost_usd"] is not None
    assert result.metadata["reasoning_effort"] == "medium"
    await service._parse("visual QA", ResearchReport, image=b"png-bytes")
    assert captured["input"][0]["content"][1]["detail"] == "high"


@pytest.mark.asyncio
async def test_openai_image_quality_defaults_to_medium() -> None:
    brief = (
        await OpenAIService(Settings()).creative(
            (await OpenAIService(Settings()).research(date.today(), "none")).value.candidates[0],
            {},
        )
    ).value
    captured = {}

    class Images:
        async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(b"image").decode())],
                quality="medium",
                size="1024x1024",
                usage=SimpleNamespace(
                    model_dump=lambda: {
                        "input_tokens_details": {"text_tokens": 50},
                        "output_tokens_details": {"image_tokens": 500},
                    }
                ),
            )

    service = OpenAIService(Settings(provider_mode="live", openai_api_key="test"))
    service.client = SimpleNamespace(images=Images())  # type: ignore[assignment]
    image, metadata = await service.artwork(brief, 1024, 1024)
    assert image == b"image"
    assert captured["quality"] == "medium"
    assert metadata["estimated_cost_usd"] == 0.01525


@pytest.mark.asyncio
async def test_openai_image_edit_preserves_requested_source_size() -> None:
    fixture = OpenAIService(Settings())
    concept = (await fixture.research(date.today(), "none")).value.candidates[0]
    brief = (await fixture.creative(concept, {})).value
    source = io.BytesIO()
    Image.new("RGBA", (32, 48), (0, 0, 0, 0)).save(source, "PNG")
    captured = {}

    class Images:
        async def edit(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(source.getvalue()).decode())],
                quality="high",
                size="32x48",
                usage=None,
            )

    service = OpenAIService(Settings(provider_mode="live", openai_api_key="test"))
    service.client = SimpleNamespace(images=Images())  # type: ignore[assignment]
    await service.revise_artwork(source.getvalue(), brief, [])
    assert captured["size"] == "32x48"


def test_openai_exhausted_credit_is_not_retried_as_transient_429() -> None:
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx2.Response(429, request=request)
    exhausted = RateLimitError(
        "no credits",
        response=response,
        body={"type": "insufficient_quota", "code": "credit_balance_exhausted"},
    )
    with pytest.raises(OpenAINonRetryableError, match="credits, spend limit, or quota"):
        OpenAIService._handle_api_error(exhausted)
    project_limit = RateLimitError(
        "project limit", response=response, body={"code": "project_spend_limit_exceeded"}
    )
    with pytest.raises(OpenAINonRetryableError, match="spend limit"):
        OpenAIService._handle_api_error(project_limit)
    transient = RateLimitError(
        "too many requests", response=response, body={"code": "rate_limit_exceeded"}
    )
    assert OpenAIService._handle_api_error(transient) is None
    bad_request = BadRequestError(
        "invalid schema", response=httpx2.Response(400, request=request), body={}
    )
    with pytest.raises(OpenAINonRetryableError, match="HTTP 400"):
        OpenAIService._handle_api_error(bad_request)


@pytest.mark.asyncio
async def test_printify_ambiguous_create_is_not_blindly_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.printify.com/v1")
    client = PrintifyClient(
        Settings(provider_mode="live", publish_mode="live", printify_api_token="token"),
        client=http,
    )
    with pytest.raises(AmbiguousCreateError):
        await client.create_product("shop", {"title": "fixture"})
    assert calls == 1
    await client.close()


@pytest.mark.asyncio
async def test_printify_orders_uses_supported_page_parameter_only() -> None:
    paths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        return httpx.Response(200, json={"data": []}, request=request)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.printify.com/v1"
    )
    client = PrintifyClient(Settings(printify_api_token="token"), client=http)
    assert (await client.orders("123", page=2))["data"] == []
    assert paths == ["https://api.printify.com/v1/shops/123/orders.json?page=2"]
    await client.close()
