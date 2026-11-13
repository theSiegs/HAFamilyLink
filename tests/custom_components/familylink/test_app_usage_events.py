"""The app usage event: an app's usage grew since the last refresh."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.familylink.event import EVENT_USAGE_GREW, FamilyLinkAppUsageEvent
from custom_components.familylink.usage_tracker import UsageGrowthTracker

START = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 10)


def _screen_time(day: date = TODAY, refreshed: datetime | None = None, **seconds: float) -> dict:
    """`com_video=600` is 600 seconds of com.video on the phone."""
    return {
        "date": day,
        "device_names": {"dev-phone": "Pixel 9 Pro", "dev-tablet": "Tab"},
        "data_refreshed_ms": str(int(refreshed.timestamp() * 1000)) if refreshed else None,
        "app_device_usage": [
            {"package": pkg.replace("_", "."), "device_id": "dev-phone", "seconds": secs} for pkg, secs in seconds.items()
        ],
    }


def test_the_first_refresh_sets_the_baseline_and_the_next_reports_the_growth():
    tracker = UsageGrowthTracker()
    assert tracker.update("child-1", _screen_time(com_video=600, com_game=300), START) == []

    now = START + timedelta(minutes=5)
    grew = tracker.update("child-1", _screen_time(com_video=900, com_game=300), now)

    assert grew == [{
        "package": "com.video",
        "device": "Pixel 9 Pro",
        "grew_minutes": 5.0,
        "today_minutes": 15.0,
        "reported_at": now.isoformat(),
    }]
    # Nothing new: nothing reported
    assert tracker.update("child-1", _screen_time(com_video=900, com_game=300), now + timedelta(minutes=1)) == []


def test_the_time_is_the_one_google_received_the_usage_at_and_never_later_than_now():
    tracker = UsageGrowthTracker()
    tracker.update("child-1", _screen_time(com_video=600), START)

    uploaded = START + timedelta(minutes=3)
    now = START + timedelta(minutes=5)
    assert tracker.update("child-1", _screen_time(TODAY, uploaded, com_video=900), now)[0]["reported_at"] == uploaded.isoformat()

    later = now + timedelta(minutes=5)
    future = later + timedelta(hours=2)
    assert tracker.update("child-1", _screen_time(TODAY, future, com_video=960), later)[0]["reported_at"] == later.isoformat()


def test_the_most_growth_comes_first_and_two_devices_are_reported_apart():
    tracker = UsageGrowthTracker()
    first = _screen_time(com_video=600, com_game=300)
    first["app_device_usage"].append({"package": "com.video", "device_id": "dev-tablet", "seconds": 60})
    tracker.update("child-1", first, START)

    second = _screen_time(com_video=660, com_game=900)
    second["app_device_usage"].append({"package": "com.video", "device_id": "dev-tablet", "seconds": 180})
    grew = tracker.update("child-1", second, START + timedelta(minutes=5))

    assert [(event["package"], event["device"], event["grew_minutes"]) for event in grew] == [
        ("com.game", "Pixel 9 Pro", 10.0),
        ("com.video", "Tab", 2.0),
        ("com.video", "Pixel 9 Pro", 1.0),
    ]


def test_a_new_day_and_a_removed_child_start_over():
    tracker = UsageGrowthTracker()
    tracker.update("child-1", _screen_time(com_video=600), START)

    # Tomorrow's first total is compared with nothing, even though it is non-zero
    assert tracker.update("child-1", _screen_time(date(2026, 10, 11), com_video=60), START + timedelta(minutes=2)) == []

    tracker.retain(set())
    assert tracker.update("child-1", _screen_time(date(2026, 10, 11), com_video=600), START + timedelta(minutes=4)) == []


def _coordinator(usage_grew: list, refresh: int):
    return SimpleNamespace(
        data={
            "children_data": [
                {
                    "child_id": "1001",
                    "child_name": "Alex",
                    "apps": [{"packageName": "com.video", "title": "Video"}],
                    "usage_grew": usage_grew,
                    "usage_refresh": refresh,
                }
            ]
        },
        last_update_success=True,
    )


GREW = {"package": "com.video", "device": "Pixel 9 Pro", "grew_minutes": 5.0, "today_minutes": 15.0, "reported_at": START.isoformat()}


def _entity(coordinator) -> tuple[FamilyLinkAppUsageEvent, list]:
    entity = FamilyLinkAppUsageEvent(coordinator, "1001", "Alex")
    fired: list = []
    entity._trigger_event = lambda event_type, data: fired.append((event_type, data))
    entity.async_write_ha_state = lambda: None
    return entity, fired


def test_each_growth_fires_one_event_with_the_app_name():
    coordinator = _coordinator([], refresh=1)
    entity, fired = _entity(coordinator)

    coordinator.data["children_data"][0].update(usage_grew=[GREW, {**GREW, "package": "com.other"}], usage_refresh=2)
    entity._handle_coordinator_update()

    assert fired == [
        (EVENT_USAGE_GREW, {"app": "Video", **GREW}),
        (EVENT_USAGE_GREW, {"app": "com.other", **GREW, "package": "com.other"}),
    ]
    assert entity.unique_id == "familylink_1001_app_usage_event"
    assert entity.event_types == [EVENT_USAGE_GREW]


def test_the_same_refresh_does_not_fire_twice_and_the_one_at_setup_is_not_news():
    coordinator = _coordinator([GREW], refresh=7)
    entity, fired = _entity(coordinator)

    entity._handle_coordinator_update()
    assert fired == []

    coordinator.data["children_data"][0]["usage_refresh"] = 8
    entity._handle_coordinator_update()
    entity._handle_coordinator_update()
    assert len(fired) == 1
