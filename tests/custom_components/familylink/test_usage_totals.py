"""Yesterday, the week before today, and when Google last got usage."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.sensor import FamilyLinkScreenTimeSensor

TARGET_DATE = datetime(2026, 10, 10, 12, 0, 0)


def _session(day: int, package: str, seconds: float, device: str = "dev-phone") -> dict:
    return {
        "usage": f"{seconds}s",
        "appId": {"androidAppPackageName": package},
        "deviceMudId": device,
        "date": {"year": 2026, "month": 10, "day": day},
    }


async def test_client_totals_every_day_and_reports_the_refresh_time(hass):
    client = FamilyLinkClient(hass, {})
    data = {
        "deviceInfo": [{"deviceId": "dev-phone", "displayInfo": {"friendlyName": "Pixel 9 Pro"}}],
        "apps": [],
        "lastActivityRefreshTimestampMillis": "1791633600000",
        "appUsageSessions": [
            _session(8, "com.video", 600),
            _session(9, "com.video", 1200),
            _session(9, "com.game", 300),
            _session(10, "com.video", 120),
        ],
    }

    result = await client.async_get_daily_screen_time("child-1", TARGET_DATE, data=data)

    assert result["total_seconds"] == 120
    assert result["daily_totals"] == {"2026-10-08": 600, "2026-10-09": 1500, "2026-10-10": 120}
    assert result["data_refreshed_ms"] == "1791633600000"


async def test_client_skips_a_session_without_a_date_and_counts_an_unreadable_usage_as_zero(hass):
    client = FamilyLinkClient(hass, {})
    no_date = _session(9, "com.video", 600)
    del no_date["date"]
    unreadable = _session(9, "com.game", 0)
    unreadable["usage"] = "soon"
    data = {
        "deviceInfo": [],
        "apps": [],
        "appUsageSessions": [no_date, unreadable, _session(9, "com.video", 60)],
    }

    result = await client.async_get_daily_screen_time("child-1", TARGET_DATE, data=data)

    assert result["daily_totals"] == {"2026-10-09": 60}
    assert result["total_seconds"] == 0


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


def test_sensor_shows_yesterday_and_the_seven_days_before_today():
    sensor = _sensor({
        "total_seconds": 120,
        "date": date(2026, 10, 10),
        "app_breakdown": {},
        # Oct 2 is eight days back and left out of the week; Oct 6 and 7 had no usage
        "daily_totals": {"2026-10-02": 6000, "2026-10-08": 600, "2026-10-09": 1500, "2026-10-10": 120},
        "data_refreshed_ms": "1791633600000",
    })

    attrs = sensor.extra_state_attributes
    assert attrs["yesterday_minutes"] == 25.0
    assert attrs["last_7_days_minutes"] == 35.0
    assert attrs["data_updated"] == datetime.fromtimestamp(1791633600, timezone.utc).isoformat()


def test_a_day_google_left_out_reads_as_zero():
    attrs = _sensor({
        "total_seconds": 0,
        "date": date(2026, 10, 10),
        "app_breakdown": {},
        "daily_totals": {"2026-10-08": 600},
    }).extra_state_attributes

    assert attrs["yesterday_minutes"] == 0.0
    assert attrs["last_7_days_minutes"] == 10.0


def test_sensor_without_earlier_days_adds_nothing():
    attrs = _sensor({"total_seconds": 120, "date": date(2026, 10, 10), "app_breakdown": {}}).extra_state_attributes

    assert "yesterday_minutes" not in attrs
    assert "last_7_days_minutes" not in attrs
    assert "data_updated" not in attrs
