"""A usage sensor per top app of a child, and per top app of each device without time limits."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.components.sensor import SensorStateClass
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.familylink import sensor as sensor_platform
from custom_components.familylink.app_usage import (
    AppUsageSettings,
    app_usage_unique_id,
    parse_app_usage_unique_id,
    top_packages,
)
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import (
    CAP_APP_ACTIVITY,
    CAPS_TIME_LIMIT,
    CONF_APP_USAGE_EXCLUDED,
    CONF_APP_USAGE_PER_CHILD,
    CONF_APP_USAGE_PINNED,
    DEFAULT_APP_USAGE_PER_CHILD,
    DEFAULT_APP_USAGE_PER_DEVICE,
    DOMAIN,
)
from custom_components.familylink.sensor import FamilyLinkAppUsageSensor, new_app_usage_sensors

PHONE = {"id": "dev-phone", "name": "Pixel 9 Pro", "capabilities": [CAPS_TIME_LIMIT[0]]}
TV = {"id": "dev-tv", "name": "Lounge TV", "capabilities": [CAP_APP_ACTIVITY]}
HOUR = 3600
TODAY = date(2026, 10, 10)


def test_top_packages_ranks_by_usage_and_skips_barely_used_apps():
    totals = {"com.a": 5 * HOUR, "com.b": 9 * HOUR, "com.c": 60, "com.d": 2 * HOUR}

    assert top_packages(totals, 2) == ["com.b", "com.a"]
    assert top_packages(totals, 10) == ["com.b", "com.a", "com.d"]
    assert top_packages(None, 3) == []
    assert top_packages(totals, 0) == []


def test_launchers_system_screens_and_excluded_apps_are_not_ranked():
    totals = {
        "com.microsoft.launcher": 9 * HOUR,
        "com.sec.android.app.launcher": 8 * HOUR,
        "com.android.systemui": 7 * HOUR,
        "com.excluded": 6 * HOUR,
        "com.video": 5 * HOUR,
    }

    assert top_packages(totals, 5, frozenset({"com.excluded"})) == ["com.video"]


def test_settings_come_from_the_options_with_defaults():
    assert AppUsageSettings.from_options({}) == AppUsageSettings(DEFAULT_APP_USAGE_PER_CHILD, DEFAULT_APP_USAGE_PER_DEVICE)
    settings = AppUsageSettings.from_options({
        CONF_APP_USAGE_PER_CHILD: 3,
        CONF_APP_USAGE_PINNED: ["com.pinned", " ", ""],
        CONF_APP_USAGE_EXCLUDED: [" com.excluded "],
    })
    assert settings.per_child == 3
    assert settings.pinned == frozenset({"com.pinned"})
    assert settings.excluded == frozenset({"com.excluded"})


def test_unique_ids_round_trip_for_a_child_and_for_a_device():
    child = app_usage_unique_id("1001", "com.google.android.youtube")
    device = app_usage_unique_id("1001", "com.google.android.youtube", "aannnppa7jx5-x")

    assert parse_app_usage_unique_id(child) == ("1001", None, "com.google.android.youtube")
    assert parse_app_usage_unique_id(device) == ("1001", "aannnppa7jx5-x", "com.google.android.youtube")
    assert parse_app_usage_unique_id("familylink_1001_top_app_3") is None


def _session(day: int, package: str, seconds: float, device: str) -> dict:
    return {
        "usage": f"{seconds}s",
        "appId": {"androidAppPackageName": package},
        "deviceMudId": device,
        "date": {"year": 2026, "month": 10, "day": day},
    }


async def test_client_totals_each_app_over_every_day_and_the_week_before_today(hass):
    data = {
        "deviceInfo": [],
        "apps": [],
        "appUsageSessions": [
            _session(1, "com.video", 6000, "dev-phone"),  # nine days back: not in the week
            _session(8, "com.video", 600, "dev-phone"),
            _session(9, "com.video", 1200, "dev-tv"),
            _session(10, "com.video", 120, "dev-tv"),  # today: not in the week
            _session(10, "com.game", 300, "dev-phone"),
        ],
    }

    result = await FamilyLinkClient(hass, {}).async_get_daily_screen_time(
        "child-1", datetime(2026, 10, 10, 12, 0), data=data
    )

    assert result["app_totals"] == {"com.video": 7920, "com.game": 300}
    assert result["device_app_totals"] == {
        "dev-phone": {"com.video": 6600, "com.game": 300},
        "dev-tv": {"com.video": 1320},
    }
    assert result["app_week_totals"] == {"com.video": 1800}
    assert result["device_app_week_totals"] == {"dev-phone": {"com.video": 600}, "dev-tv": {"com.video": 1200}}


def _screen_time(**overrides) -> dict:
    screen_time = {
        "date": TODAY,
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
        "app_week_totals": {"com.video": 2 * HOUR},
        "device_app_week_totals": {"dev-tv": {"com.video": HOUR}},
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
        async_add_listener=lambda update, context=None: lambda: None,
    )


def _set_today(coordinator, **app_seconds):
    coordinator.data["children_data"][0]["screen_time"]["app_breakdown"] = app_seconds


def test_a_childs_sensor_counts_the_minutes_used_today_over_all_devices():
    sensor = FamilyLinkAppUsageSensor(_coordinator(), "1001", "Alex", "com.video")

    assert sensor.native_value == 10.0
    # The child's hub device name comes first
    assert sensor.name == "Video usage today"
    assert sensor.has_entity_name
    assert sensor.unique_id == "familylink_1001_app_usage_com.video"
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.extra_state_attributes == {
        "package": "com.video",
        "last_7_days_minutes": 120.0,
        "by_device": {"Pixel 9 Pro": 2.0, "Lounge TV": 8.0},
    }


def test_a_device_sensor_counts_only_that_device_and_names_the_child():
    sensor = FamilyLinkAppUsageSensor(
        _coordinator(), "1001", "Alex", "com.video", device_id="dev-tv", device_name="Lounge TV"
    )

    assert sensor.native_value == 8.0
    # The device name comes first; several children can share the device
    assert sensor.name == "Alex Video usage today"
    assert sensor.extra_state_attributes == {"package": "com.video", "last_7_days_minutes": 60.0}
    assert ("familylink", "1001_dev-tv") in sensor.device_info["identifiers"]


def test_the_value_never_goes_down_during_the_day_and_starts_over_the_next():
    coordinator = _coordinator()
    sensor = FamilyLinkAppUsageSensor(coordinator, "1001", "Alex", "com.video")
    sensor.async_write_ha_state = lambda: None
    assert sensor.native_value == 10.0

    # The app briefly missing from Google's answer does not read as a new count
    _set_today(coordinator, **{"com.game": 300})
    sensor._handle_coordinator_update()
    assert sensor.native_value == 10.0

    _set_today(coordinator, **{"com.video": 900})
    sensor._handle_coordinator_update()
    assert sensor.native_value == 15.0

    # A new day starts over
    coordinator.data["children_data"][0]["screen_time"]["date"] = date(2026, 10, 11)
    _set_today(coordinator, **{"com.video": 60})
    sensor._handle_coordinator_update()
    assert sensor.native_value == 1.0


def test_an_app_not_used_today_reads_zero_and_missing_data_reads_unavailable():
    sensor = FamilyLinkAppUsageSensor(_coordinator(), "1001", "Alex", "com.unused")
    assert sensor.native_value == 0.0
    assert sensor.available
    assert sensor.extra_state_attributes == {"package": "com.unused", "last_7_days_minutes": 0.0}

    no_data = FamilyLinkAppUsageSensor(_coordinator(screen_time={}), "1001", "Alex", "com.video")
    assert no_data.native_value is None
    assert not no_data.available


async def test_the_days_highest_value_survives_a_restart(hass):
    sensor = FamilyLinkAppUsageSensor(_coordinator(), "1001", "Alex", "com.video")
    sensor.hass = hass
    sensor.entity_id = "sensor.alex_video_usage_today"
    today_at_noon = datetime(2026, 10, 10, 12, 0).astimezone()
    mock_restore_cache(hass, [State(sensor.entity_id, "25.0", last_changed=today_at_noon, last_updated=today_at_noon)])

    await sensor.async_added_to_hass()

    assert sensor.native_value == 25.0


async def test_yesterdays_value_is_not_restored(hass):
    sensor = FamilyLinkAppUsageSensor(_coordinator(), "1001", "Alex", "com.video")
    sensor.hass = hass
    sensor.entity_id = "sensor.alex_video_usage_today"
    yesterday = datetime(2026, 10, 9, 22, 0).astimezone()
    mock_restore_cache(hass, [State(sensor.entity_id, "95.0", last_changed=yesterday, last_updated=yesterday)])

    await sensor.async_added_to_hass()

    assert sensor.native_value == 10.0


def test_the_top_apps_of_the_child_and_of_the_tv_get_a_sensor_and_the_phone_does_not():
    created = new_app_usage_sensors(_coordinator(), set(), set())

    assert sorted(sensor.unique_id for sensor in created) == sorted([
        "familylink_1001_app_usage_com.video",
        "familylink_1001_app_usage_com.game",
        "familylink_1001_dev-tv_app_usage_com.video",
    ])


def test_the_options_set_the_counts_and_pinned_and_excluded_apps():
    many = {f"com.app{n}": (100 - n) * HOUR for n in range(30)}
    settings = AppUsageSettings(per_child=2, per_device=0, pinned=frozenset({"com.pinned"}), excluded=frozenset({"com.app0"}))

    created = new_app_usage_sensors(_coordinator(_screen_time(app_totals=many)), set(), set(), settings)

    assert [sensor.unique_id for sensor in created] == [
        "familylink_1001_app_usage_com.pinned",
        "familylink_1001_app_usage_com.app1",
        "familylink_1001_app_usage_com.app2",
    ]


def test_the_default_counts_cap_the_ranking():
    many = {f"com.app{n}": (100 - n) * HOUR for n in range(30)}
    created = new_app_usage_sensors(_coordinator(_screen_time(app_totals=many, device_app_totals={})), set(), set())
    assert len(created) == DEFAULT_APP_USAGE_PER_CHILD

    tv_many = {f"com.tv{n}": (100 - n) * HOUR for n in range(30)}
    created = new_app_usage_sensors(_coordinator(_screen_time(app_totals={}, device_app_totals={"dev-tv": tv_many})), set(), set())
    assert len(created) == DEFAULT_APP_USAGE_PER_DEVICE


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


async def test_setup_restores_registered_sensors_and_adds_newly_ranked_apps(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_APP_USAGE_PER_CHILD: 1})
    entry.add_to_hass(hass)
    coordinator = _coordinator(devices=[])
    listeners = []
    coordinator.async_add_listener = lambda update, context=None: listeners.append(update) or (lambda: None)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "familylink_1001_app_usage_com.old", config_entry=entry
    )
    added: list = []

    with patch.object(sensor_platform, "ensure_child_device"), patch.object(sensor_platform, "async_prune_entities"):
        await sensor_platform.async_setup_entry(hass, entry, lambda entities, *args, **kwargs: added.extend(entities))

    usage = sorted(entity.unique_id for entity in added if isinstance(entity, FamilyLinkAppUsageSensor))
    # One ranked app (the option says 1) and the one from the registry
    assert usage == ["familylink_1001_app_usage_com.old", "familylink_1001_app_usage_com.video"]

    added.clear()
    coordinator.data["children_data"][0]["screen_time"]["app_totals"] = {"com.new": 50 * HOUR}
    listeners[0]()

    assert [entity.unique_id for entity in added] == ["familylink_1001_app_usage_com.new"]
