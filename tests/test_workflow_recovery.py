from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from merch.schemas import ApprovalSignal, Channel, PublishStatus, RunInput, RunStatus
from merch.temporal import MerchWorkflow


@pytest.mark.asyncio
@pytest.mark.parametrize("patched,successful,expected", [
    (True, True, RunStatus.PUBLISHED.value),
    (True, False, RunStatus.AWAITING_BRIEF_REVISION.value),
    (False, False, RunStatus.REJECTED.value),
])
async def test_requested_regeneration_recovers_or_preserves_old_workflow_history(
    monkeypatch: pytest.MonkeyPatch, patched: bool, successful: bool, expected: str,
) -> None:
    workflow = MerchWorkflow()
    calls: list[tuple[str, Any]] = []
    generations = 0
    rewrites = 0

    async def execute(name: str, argument: Any, **kwargs: Any) -> Any:
        nonlocal generations, rewrites
        calls.append((name, argument))
        if name == "research_run":
            return None
        if name == "screen_and_select_run":
            return True
        if name == "generate_package_run":
            generations += 1
            return generations == 1 or (successful and generations == 4)
        if name == "rewrite_failed_brief":
            rewrites += 1
            # The activity owns the existing rewrite cap. Its terminal result
            # must stop this workflow without another generation/publication.
            if not successful and rewrites == 2:
                return RunStatus.AWAITING_BRIEF_REVISION.value
            return RunStatus.PENDING.value
        if name == "automatic_approval_signal":
            if generations == 1:
                return None
            return ApprovalSignal(
                channels=[Channel.ETSY], expected_version=4, actor="system", ip_attested=False,
            )
        if name == "record_approval":
            assert argument["signal"]["expected_version"] == 4
            return True
        if name == "revalidate_approval":
            return True
        if name == "publish_channel":
            return PublishStatus.DRY_RUN
        if name in {"finish_publishing", "record_rejection"}:
            return None
        raise AssertionError(f"Unexpected workflow activity: {name}")

    async def wait_condition(predicate: Any) -> None:
        if predicate():
            return
        if generations == 1:
            await workflow.regenerate()
        else:
            assert not patched, "New failures must recover or terminate before waiting again"
            await workflow.reject("test-admin")
        assert predicate()

    def patch(identifier: str) -> bool:
        assert identifier == "artwork-effects-regeneration-recovery-v1"
        return patched

    monkeypatch.setattr("merch.temporal.workflow.execute_activity", execute)
    monkeypatch.setattr("merch.temporal.workflow.wait_condition", wait_condition)
    monkeypatch.setattr("merch.temporal.workflow.patched", patch)
    value = RunInput(run_id=uuid4(), scheduled_for=datetime.now(UTC), manual=True)
    assert await workflow.run(value) == expected

    names = [name for name, _ in calls]
    assert names.count("research_run") == names.count("screen_and_select_run") == 1
    generation_calls = [argument for name, argument in calls if name == "generate_package_run"]
    assert generation_calls[1] == {"run_id": str(value.run_id), "regenerate": True}
    if patched:
        assert rewrites == 2
        assert all(argument == {
            "run_id": str(value.run_id), "regenerate": False, "preserve_brief": True,
        } for argument in generation_calls[2:])
    else:
        assert rewrites == 0
        assert generations == 2
    assert names.count("publish_channel") == int(successful)
