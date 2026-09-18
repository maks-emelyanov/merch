from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from merch.schemas import ApprovalSignal, Channel, PublishStatus, RunInput
from merch.temporal import MerchWorkflow

pytestmark = [
    pytest.mark.temporal,
    pytest.mark.skipif(os.getenv("RUN_TEMPORAL_TESTS") != "1", reason="opt-in Temporal test"),
]


@activity.defn(name="research_run")
async def fake_research(_: str) -> None:
    pass


@activity.defn(name="screen_and_select_run")
async def fake_screen(_: str) -> bool:
    return True


@activity.defn(name="generate_package_run")
async def fake_generate(_: dict[str, object]) -> bool:
    return True


@activity.defn(name="record_approval")
async def fake_approve(_: dict[str, object]) -> bool:
    return True


@activity.defn(name="revalidate_approval")
async def fake_revalidate(_: str) -> bool:
    return True


@activity.defn(name="publish_channel")
async def fake_publish(_: object) -> PublishStatus:
    return PublishStatus.DRY_RUN


@activity.defn(name="finish_publishing")
async def fake_finish(_: dict[str, object]) -> None:
    pass


@activity.defn(name="record_rejection")
async def fake_reject(_: dict[str, str]) -> None:
    pass


@activity.defn(name="mark_failed")
async def fake_failed(_: dict[str, str]) -> None:
    pass


@activity.defn(name="mark_cancelled")
async def fake_cancelled(_: str) -> None:
    pass


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.asyncio
async def test_time_skipping_workflow_uses_optional_approval(automatic: bool) -> None:
    @activity.defn(name="automatic_approval_signal")
    async def fake_automatic_approval(_: str) -> ApprovalSignal | None:
        if not automatic:
            return None
        return ApprovalSignal(
            channels=[Channel.SHOPIFY],
            expected_version=1,
            ip_attested=False,
            actor="system",
        )

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue="test",
            workflows=[MerchWorkflow],
            activities=[
                fake_research,
                fake_screen,
                fake_generate,
                fake_automatic_approval,
                fake_approve,
                fake_revalidate,
                fake_publish,
                fake_finish,
                fake_reject,
                fake_failed,
                fake_cancelled,
            ],
        ):
            input = RunInput(
                run_id=uuid4(), scheduled_for=await environment.get_current_time(), manual=True
            )
            handle = await environment.client.start_workflow(
                MerchWorkflow.run, input, id=f"test-{input.run_id}", task_queue="test"
            )
            await environment.sleep(timedelta(seconds=1))
            if not automatic:
                await handle.signal(
                    MerchWorkflow.approve,
                    ApprovalSignal(
                        channels=[Channel.SHOPIFY],
                        expected_version=1,
                        ip_attested=True,
                        actor="test",
                    ),
                )
            assert await handle.result() == "published"
