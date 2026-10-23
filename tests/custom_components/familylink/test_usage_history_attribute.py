"""The per-day history of the daily screen time sensor."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from custom_components.familylink.sensor import FamilyLinkScreenTimeSensor


def _sensor(screen_time: dict) -> FamilyLinkScreenTimeSensor:
    coordinator = SimpleNamespace(
        data={
            "children_data": [
                {"child_id": "child-1", "child_name": "Alex", "apps": [], "screen_time": screen_time}
            ]
        },
        child_device_ids={},
        last_update_success=True,
    )
    return FamilyLinkScreenTimeSensor(coordinator, "total", child_id="child-1", child_name="Alex")


def test_history_lists_the_earlier_days_in_minutes_and_leaves_today_out():
    attrs = _sensor({
        "total_seconds": 120,
        "date": date(2026, 10, 10),
        "app_breakdown": {},
        "daily_totals": {"2026-09-12": 6000, "2026-10-08": 600, "2026-10-09": 1500, "2026-10-10": 120},
    }).extra_state_attributes

    assert attrs["history"] == {"2026-09-12": 100.0, "2026-10-08": 10.0, "2026-10-09": 25.0}


def test_history_is_not_stored_by_the_recorder():
    assert "history" in FamilyLinkScreenTimeSensor._unrecorded_attributes


def test_no_history_without_earlier_days():
    attrs = _sensor({"total_seconds": 120, "date": date(2026, 10, 10), "app_breakdown": {}}).extra_state_attributes

    assert "history" not in attrs
