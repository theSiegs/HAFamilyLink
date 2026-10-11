"""Earlier days of usage, when Google last got usage, and recently used apps."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.familylink import coordinator as coordinator_module
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator
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


def _sensor(screen_time: dict, recent_apps: list | None = None) -> FamilyLinkScreenTimeSensor:
    coordinator = SimpleNamespace(
        data={
            "children_data": [
                {
                    "child_id": "child-1",
                    "child_name": "Alex",
                    "apps": [{"packageName": "com.video", "title": "Video"}],
                    "screen_time": screen_time,
                    "recent_apps": recent_apps or [],
                }
            ]
        },
        child_device_ids={},
        last_update_success=True,
    )
    return FamilyLinkScreenTimeSensor(coordinator, "total", child_id="child-1", child_name="Alex")


def test_sensor_shows_yesterday_the_last_7_days_and_the_history():
    sensor = _sensor({
        "total_seconds": 120,
        "date": date(2026, 10, 10),
        "app_breakdown": {},
        "daily_totals": {"2026-10-01": 6000, "2026-10-08": 600, "2026-10-09": 1500, "2026-10-10": 120},
        "data_refreshed_ms": "1791633600000",
    })

    attrs = sensor.extra_state_attributes
    assert attrs["yesterday_minutes"] == 25.0
    # Today and the six days before it; Oct 1 is outside the week
    assert attrs["last_7_days_minutes"] == 37.0
    assert attrs["history"] == {"2026-10-01": 100.0, "2026-10-08": 10.0, "2026-10-09": 25.0}
    assert attrs["data_updated"] == datetime.fromtimestamp(1791633600, timezone.utc).isoformat()


def test_sensor_names_the_recent_apps():
    recent = [{"package": "com.video", "device_id": "dev-phone", "device": "Pixel 9 Pro", "last_active": "2026-10-10T16:00:00+00:00"}]
    sensor = _sensor({"total_seconds": 120, "date": date(2026, 10, 10), "app_breakdown": {}}, recent)

    assert sensor.extra_state_attributes["recent_apps"] == [{"name": "Video", **recent[0]}]


def test_sensor_without_history_adds_nothing():
    attrs = _sensor({"total_seconds": 120, "date": date(2026, 10, 10), "app_breakdown": {}}).extra_state_attributes
    assert "history" not in attrs
    assert "data_updated" not in attrs
    assert "recent_apps" not in attrs


def _screen_time(day: date, **seconds: float) -> dict:
    return {
        "date": day,
        "device_names": {"dev-phone": "Pixel 9 Pro"},
        "app_device_usage": [
            {"package": pkg.replace("_", "."), "device_id": "dev-phone", "seconds": secs} for pkg, secs in seconds.items()
        ],
    }


def test_an_app_is_recent_when_its_usage_grows(monkeypatch):
    clock = [datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: clock[0])
    coordinator = FamilyLinkDataUpdateCoordinator.__new__(FamilyLinkDataUpdateCoordinator)
    coordinator._usage_seen = {}
    coordinator._usage_last_grew = {}
    today = date(2026, 10, 10)

    # The first refresh only sets the baseline
    assert coordinator._track_recent_usage("child-1", _screen_time(today, com_video=600, com_game=300)) == []

    clock[0] += timedelta(minutes=5)
    recent = coordinator._track_recent_usage("child-1", _screen_time(today, com_video=900, com_game=300))
    assert recent == [{"package": "com.video", "device_id": "dev-phone", "device": "Pixel 9 Pro", "last_active": clock[0].isoformat()}]

    # Still listed while within the window, gone after it
    clock[0] += timedelta(minutes=29)
    assert [app["package"] for app in coordinator._track_recent_usage("child-1", _screen_time(today, com_video=900, com_game=300))] == ["com.video"]
    clock[0] += timedelta(minutes=2)
    assert coordinator._track_recent_usage("child-1", _screen_time(today, com_video=900, com_game=300)) == []


def test_a_new_day_does_not_count_as_use(monkeypatch):
    clock = [datetime(2026, 10, 10, 23, 59, tzinfo=timezone.utc)]
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: clock[0])
    coordinator = FamilyLinkDataUpdateCoordinator.__new__(FamilyLinkDataUpdateCoordinator)
    coordinator._usage_seen = {}
    coordinator._usage_last_grew = {}

    coordinator._track_recent_usage("child-1", _screen_time(date(2026, 10, 10), com_video=600))
    clock[0] += timedelta(minutes=2)
    # Tomorrow's first total is compared with nothing, even though it is non-zero
    assert coordinator._track_recent_usage("child-1", _screen_time(date(2026, 10, 11), com_video=60)) == []
