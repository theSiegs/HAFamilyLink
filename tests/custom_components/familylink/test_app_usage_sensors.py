"""A usage sensor per top app of a child, and per top app of each TV."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from homeassistant.components.sensor import SensorStateClass

from custom_components.familylink.app_usage import (
    APP_USAGE_PER_CHILD,
    APP_USAGE_PER_TV,
    app_usage_unique_id,
    parse_app_usage_unique_id,
    top_packages,
)
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CAP_APP_ACTIVITY, CAPS_TIME_LIMIT
from custom_components.familylink.sensor import FamilyLinkAppUsageSensor, new_app_usage_sensors

PHONE = {"id": "dev-phone", "name": "Pixel 9 Pro", "capabilities": [CAPS_TIME_LIMIT[0]]}
TV = {"id": "dev-tv", "name": "Lounge TV", "capabilities": [CAP_APP_ACTIVITY]}
HOUR = 3600


def test_top_packages_ranks_by_usage_and_skips_barely_used_apps():
    totals = {"com.a": 5 * HOUR, "com.b": 9 * HOUR, "com.c": 60, "com.d": 2 * HOUR}

    assert top_packages(totals, 2) == ["com.b", "com.a"]
    assert top_packages(totals, 10) == ["com.b", "com.a", "com.d"]
    assert top_packages(None, 3) == []


def test_unique_ids_round_trip_for_a_child_and_for_a_device():
    child = app_usage_unique_id("1001", "com.google.android.youtube")
    device = app_usage_unique_id("1001", "com.google.android.youtube", "aannnppa7jx5-x")

    assert parse_app_usage_unique_id(child) == ("1001", None, "com.google.android.youtube")
    assert parse_app_usage_unique_id(device) == ("1001", "aannnppa7jx5-x", "com.google.android.youtube")
    assert parse_app_usage_unique_id("familylink_1001_top_app_3") is None


async def test_client_totals_each_app_over_every_day_and_per_device(hass):
    def session(day: int, package: str, seconds: float, device: str) -> dict:
        return {
            "usage": f"{seconds}s",
            "appId": {"androidAppPackageName": package},
            "deviceMudId": device,
            "date": {"year": 2026, "month": 10, "day": day},
        }

    data = {
        "deviceInfo": [],
        "apps": [],
        "appUsageSessions": [
            session(8, "com.video", 600, "dev-phone"),
            session(9, "com.video", 1200, "dev-tv"),
            session(10, "com.video", 120, "dev-tv"),
            session(10, "com.game", 300, "dev-phone"),
        ],
    }

    result = await FamilyLinkClient(hass, {}).async_get_daily_screen_time(
        "child-1", datetime(2026, 10, 10, 12, 0), data=data
    )

    assert result["app_totals"] == {"com.video": 1920, "com.game": 300}
    assert result["device_app_totals"] == {
        "dev-phone": {"com.video": 600, "com.game": 300},
        "dev-tv": {"com.video": 1320},
    }


def _screen_time(**overrides) -> dict:
    screen_time = {
        "date": date(2026, 10, 10),
        "total_seconds": 900,
        "app_breakdown": {"com.video": 600, "com.game": 300},
        "device_names": {"dev-phone": "Pixel 9 Pro", "dev-tv": "Lounge TV"},
        "app_device_usage": [
            {"package": "com.video", "device_id": "dev-phone", "seconds": 120},
            {"package": "com.video", "device_id": "dev-tv", "seconds": 480},
            {"package": "com.game", "device_id": "dev-phone", "seconds": 300},
        ],
        "device_screen_time": {
            "dev-phone": {"app_breakdown": {"com.video": 120, "com.game": 300}},
            "dev-tv": {"app_breakdown": {"com.video": 480}},
        },
        "app_totals": {"com.video": 10 * HOUR, "com.game": 3 * HOUR, "com.tiny": 30},
        "device_app_totals": {"dev-tv": {"com.video": 8 * HOUR, "com.tiny": 30}, "dev-phone": {"com.game": 3 * HOUR}},
    }
    screen_time.update(overrides)
    return screen_time


def _coordinator(screen_time: dict | None = None, devices: list | None = None):
    return SimpleNamespace(
        data={
            "children_data": [
                {
                    "child_id": "1001",
                    "child_name": "Alex",
                    "apps": [
                        {"packageName": "com.video", "title": "Video"},
                        {"packageName": "com.game", "title": "Game"},
                    ],
                    "screen_time": _screen_time() if screen_time is None else screen_time,
                    "devices": [PHONE, TV] if devices is None else devices,
                }
            ]
        },
        child_device_ids={},
        last_update_success=True,
    )


def test_a_childs_sensor_counts_the_minutes_used_today_over_all_devices():
    sensor = FamilyLinkAppUsageSensor(_coordinator(), "1001", "Alex", "com.video")

    assert sensor.native_value == 10.0
    assert sensor.name == "Alex Video usage today"
    assert sensor.unique_id == "familylink_1001_app_usage_com.video"
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.extra_state_attributes == {
        "package": "com.video",
        "by_device": {"Pixel 9 Pro": 2.0, "Lounge TV": 8.0},
    }


def test_a_tv_sensor_counts_only_that_device_and_names_the_child():
    sensor = FamilyLinkAppUsageSensor(
        _coordinator(), "1001", "Alex", "com.video", device_id="dev-tv", device_name="Lounge TV"
    )

    assert sensor.native_value == 8.0
    assert sensor.name == "Alex Video on Lounge TV"
    assert sensor.extra_state_attributes == {"package": "com.video"}
    assert ("familylink", "1001_dev-tv") in sensor.device_info["identifiers"]


def test_an_app_not_used_today_reads_zero_and_missing_data_reads_unavailable():
    sensor = FamilyLinkAppUsageSensor(_coordinator(), "1001", "Alex", "com.unused")
    assert sensor.native_value == 0.0
    assert sensor.available

    no_data = FamilyLinkAppUsageSensor(_coordinator(screen_time={}), "1001", "Alex", "com.video")
    assert no_data.native_value is None
    assert not no_data.available


def test_the_top_apps_of_the_child_and_of_the_tv_get_a_sensor_and_the_phone_does_not():
    created = new_app_usage_sensors(_coordinator(), set(), set())

    assert sorted(sensor.unique_id for sensor in created) == sorted([
        "familylink_1001_app_usage_com.video",
        "familylink_1001_app_usage_com.game",
        "familylink_1001_dev-tv_app_usage_com.video",
    ])


def test_only_the_configured_number_of_apps_is_ranked():
    many = {f"com.app{n}": (100 - n) * HOUR for n in range(30)}
    created = new_app_usage_sensors(_coordinator(_screen_time(app_totals=many, device_app_totals={})), set(), set())

    assert len(created) == APP_USAGE_PER_CHILD
    tv_many = {f"com.tv{n}": (100 - n) * HOUR for n in range(30)}
    created = new_app_usage_sensors(_coordinator(_screen_time(app_totals={}, device_app_totals={"dev-tv": tv_many})), set(), set())
    assert len(created) == APP_USAGE_PER_TV


def test_an_app_is_added_once_and_a_newly_ranked_one_later():
    coordinator = _coordinator()
    known: set[str] = set()
    assert len(new_app_usage_sensors(coordinator, known, set())) == 3
    assert new_app_usage_sensors(coordinator, known, set()) == []

    coordinator.data["children_data"][0]["screen_time"]["app_totals"]["com.new"] = 20 * HOUR
    later = new_app_usage_sensors(coordinator, known, set())

    assert [sensor.unique_id for sensor in later] == ["familylink_1001_app_usage_com.new"]


def test_a_sensor_from_the_registry_stays_when_its_app_leaves_the_ranking():
    remembered = {("1001", None, "com.old"), ("1001", "dev-tv", "com.old"), ("1001", "dev-gone", "com.old"), ("9999", None, "com.x")}

    created = new_app_usage_sensors(_coordinator(), set(), remembered)

    ids = {sensor.unique_id for sensor in created}
    # Another child's sensor and one of a device that is gone are not added here
    assert {"familylink_1001_app_usage_com.old", "familylink_1001_dev-tv_app_usage_com.old"} <= ids
    assert not any("com.x" in unique_id or "dev-gone" in unique_id for unique_id in ids)


def test_a_phone_without_a_capability_list_is_not_taken_for_a_tv():
    no_caps = {"id": "dev-phone", "name": "Old phone"}
    screen_time = _screen_time(app_totals={}, device_app_totals={"dev-phone": {"com.game": 3 * HOUR}})

    assert new_app_usage_sensors(_coordinator(screen_time, devices=[no_caps]), set(), set()) == []
