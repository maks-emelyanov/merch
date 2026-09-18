from __future__ import annotations

from types import SimpleNamespace

import pytest
from temporalio.client import ScheduleState

from merch.config import Settings
from merch.temporal import reconcile_schedules


@pytest.mark.asyncio
async def test_both_daily_schedules_run_at_930_and_keep_pause_state(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeHandle:
        def __init__(self, state: ScheduleState) -> None:
            self.state = state
            self.schedule = None

        async def describe(self):  # type: ignore[no-untyped-def]
            return SimpleNamespace(schedule=SimpleNamespace(state=self.state))

        async def update(self, callback):  # type: ignore[no-untyped-def]
            description = await self.describe()
            self.schedule = callback(SimpleNamespace(description=description)).schedule

    handles = {
        "merch-daily-design": FakeHandle(
            ScheduleState(paused=True, note="Billing pause")
        ),
        "merch-daily-analytics": FakeHandle(ScheduleState(paused=False)),
    }

    class FakeClient:
        def get_schedule_handle(self, schedule_id):  # type: ignore[no-untyped-def]
            return handles[schedule_id]

    async def fake_temporal_client(settings):  # type: ignore[no-untyped-def]
        return FakeClient()

    monkeypatch.setattr("merch.temporal.temporal_client", fake_temporal_client)
    await reconcile_schedules(Settings(_env_file=None))

    for handle in handles.values():
        assert handle.schedule is not None
        assert handle.schedule.spec.cron_expressions == ["30 9 * * *"]
        assert handle.schedule.spec.time_zone_name == "America/New_York"
    assert handles["merch-daily-design"].schedule.state.paused
    assert handles["merch-daily-design"].schedule.state.note == "Billing pause"
    assert not handles["merch-daily-analytics"].schedule.state.paused
