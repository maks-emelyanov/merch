from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from playwright.sync_api import Page

from merch.config import get_settings
from merch.database import get_engine, session_scope
from merch.defaults import fixture_product_template
from merch.domain.prepress import make_fixture_art
from merch.models import Base
from merch.repository import ConfigurationRepository, RunRepository
from merch.schemas import RunInput, RunStatus
from merch.services.storage import ArtifactStorage

pytestmark = [
    pytest.mark.playwright,
    pytest.mark.skipif(os.getenv("RUN_PLAYWRIGHT") != "1", reason="opt-in browser test"),
]


@pytest.fixture
def live_server(isolated_app, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    monkeypatch.setenv("MERCH_MANUAL_APPROVAL_ENABLED", "true")
    get_settings.cache_clear()
    Base.metadata.create_all(get_engine())
    value = RunInput(run_id=uuid4(), scheduled_for=datetime.now(UTC), manual=True)
    storage = ArtifactStorage(get_settings())
    storage.ensure_bucket()
    key, digest = storage.put(make_fixture_art(80, 100))
    with session_scope() as session:
        ConfigurationRepository(session).save_template(fixture_product_template())
        repository = RunRepository(session)
        run = repository.create(value, f"browser-{value.run_id}")
        run.status = RunStatus.AWAITING_APPROVAL.value
        run.selected_concept = {"concept_name": "Browser Fixture"}
        run.qa_report = {
            "passed": True,
            "revision": 1,
            "issues": [],
            "width": 80,
            "height": 100,
            "has_alpha": True,
            "color_profile": "sRGB IEC61966-2.1",
        }
        run.ip_report = {
            "status": "pass",
            "risk_score": 0,
            "matches": [],
            "uspto_search_url": "https://tmsearch.uspto.gov/",
        }
        run.listings = {
            "listings": [
                {
                    "channel": channel,
                    "title": "Browser Fixture T-Shirt",
                    "short_description": "Fixture listing",
                    "tags": ["fixture"],
                }
                for channel in ("shopify", "etsy", "amazon_us")
            ]
        }
        run.price_quotes = []
        repository.add_artifact(
            str(value.run_id),
            kind="production-v1",
            revision=1,
            object_key=key,
            sha256=digest,
            width=80,
            height=100,
            metadata={},
        )
    process = subprocess.Popen(
        ["uv", "run", "uvicorn", "merch.web:app", "--host", "127.0.0.1", "--port", "8765"],
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = "http://127.0.0.1:8765"
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"{base_url}/health/ready", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("test server did not become ready")
        yield base_url, str(value.run_id)
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_operator_can_review_artwork_and_reach_protected_approval(
    page: Page, live_server: tuple[str, str]
) -> None:
    base_url, run_id = live_server
    page.goto(f"{base_url}/login")
    page.get_by_label("Password").fill("test-password")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(re.compile(r"/$"))
    assert page.get_by_text("Production history").is_visible()
    page.goto(f"{base_url}/runs/{run_id}")
    assert page.get_by_text("Human release gate").is_visible()
    assert page.locator(".checker img").is_visible()
    page.get_by_label("Shopify").check()
    page.get_by_label("Type PUBLISH").fill("PUBLISH")
    assert page.locator("#ip-attested").count() == 0
    assert page.get_by_text("IP screen:").count() == 0
    assert page.locator("#approval-form").evaluate("form => form.checkValidity()") is True
