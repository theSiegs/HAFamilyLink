"""Apps whose usage grew in the last 30 minutes, from Google's daily totals."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.familylink.sensor import FamilyLinkScreenTimeSensor
from custom_components.familylink.usage_tracker import RecentUsageTracker

START = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)


def _screen_time(day: date, refreshed: datetime | None = None, **seconds: float) -> dict:
    """`com_video=600` is 600 seconds of com.video on the phone."""
    return {
        "date": day,
        "device_names": {"dev-phone": "Pixel 9 Pro", "dev-tablet": "Tab"},
        "data_refreshed_ms": str(int(refreshed.timestamp() * 1000)) if refreshed else None,
        "app_device_usage": [
            {"package": pkg.replace("_", "."), "device_id": "dev-phone", "seconds": secs} for pkg, secs in seconds.items()
        ],
    }


TODAY = date(2026, 10, 10)


def test_an_app_is_listed_with_how_much_it_grew_when_its_usage_grows():
    tracker = RecentUsageTracker()

    # The first refresh only sets the baseline
    assert tracker.update("child-1", _screen_time(TODAY, com_video=600, com_game=300), START) == []

    now = START + timedelta(minutes=5)
    recent = tracker.update("child-1", _screen_time(TODAY, com_video=900, com_game=300), now)

    assert recent == [{
        "package": "com.video",
        "device": "Pixel 9 Pro",
        "grew_minutes": 5.0,
        "today_minutes": 15.0,
        "reported_at": now.isoformat(),
    }]


def test_the_time_is_the_one_google_received_the_usage_at():
    tracker = RecentUsageTracker()
    tracker.update("child-1", _screen_time(TODAY, com_video=600), START)

    uploaded = START + timedelta(minutes=3)
    now = START + timedelta(minutes=5)
    recent = tracker.update("child-1", _screen_time(TODAY, uploaded, com_video=900), now)

    assert recent[0]["reported_at"] == uploaded.isoformat()


def test_a_time_from_the_future_is_not_believed():
    tracker = RecentUsageTracker()
    tracker.update("child-1", _screen_time(TODAY, com_video=600), START)

    now = START + timedelta(minutes=5)
    recent = tracker.update("child-1", _screen_time(TODAY, now + timedelta(hours=2), com_video=900), now)

    assert recent[0]["reported_at"] == now.isoformat()


def test_growth_adds_up_inside_the_window_and_then_expires():
    tracker = RecentUsageTracker()
    tracker.update("child-1", _screen_time(TODAY, com_video=600), START)
    tracker.update("child-1", _screen_time(TODAY, com_video=900), START + timedelta(minutes=5))
    recent = tracker.update("child-1", _screen_time(TODAY, com_video=1080), START + timedelta(minutes=10))

    assert recent[0]["grew_minutes"] == 8.0
    assert recent[0]["today_minutes"] == 18.0

    # Still listed 29 minutes after the last growth, gone after 31
    unchanged = _screen_time(TODAY, com_video=1080)
    assert len(tracker.update("child-1", unchanged, START + timedelta(minutes=39))) == 1
    assert tracker.update("child-1", unchanged, START + timedelta(minutes=41)) == []


def test_growth_after_the_window_starts_over():
    tracker = RecentUsageTracker()
    tracker.update("child-1", _screen_time(TODAY, com_video=600), START)
    tracker.update("child-1", _screen_time(TODAY, com_video=900), START + timedelta(minutes=5))

    later = START + timedelta(hours=2)
    recent = tracker.update("child-1", _screen_time(TODAY, com_video=960), later)

    assert recent[0]["grew_minutes"] == 1.0


def test_the_newest_growth_comes_first():
    tracker = RecentUsageTracker()
    tracker.update("child-1", _screen_time(TODAY, com_video=600, com_game=300), START)
    tracker.update("child-1", _screen_time(TODAY, com_video=900, com_game=300), START + timedelta(minutes=5))
    recent = tracker.update("child-1", _screen_time(TODAY, com_video=900, com_game=600), START + timedelta(minutes=10))

    assert [app["package"] for app in recent] == ["com.game", "com.video"]


def test_a_new_day_does_not_count_as_use():
    tracker = RecentUsageTracker()
    tracker.update("child-1", _screen_time(date(2026, 10, 10), com_video=600), START)

    # Tomorrow's first total is compared with nothing, even though it is non-zero
    assert tracker.update("child-1", _screen_time(date(2026, 10, 11), com_video=60), START + timedelta(minutes=2)) == []


def test_the_same_app_on_two_devices_is_listed_twice():
    tracker = RecentUsageTracker()
    first = _screen_time(TODAY, com_video=600)
    first["app_device_usage"].append({"package": "com.video", "device_id": "dev-tablet", "seconds": 60})
    tracker.update("child-1", first, START)

    second = _screen_time(TODAY, com_video=900)
    second["app_device_usage"].append({"package": "com.video", "device_id": "dev-tablet", "seconds": 120})
    recent = tracker.update("child-1", second, START + timedelta(minutes=5))

    assert {(app["device"], app["grew_minutes"]) for app in recent} == {("Pixel 9 Pro", 5.0), ("Tab", 1.0)}


def test_children_do_not_share_totals_and_a_removed_child_is_forgotten():
    tracker = RecentUsageTracker()
    tracker.update("child-1", _screen_time(TODAY, com_video=600), START)

    # child-2 starts with its own baseline: a high first total is not growth
    assert tracker.update("child-2", _screen_time(TODAY, com_video=9000), START + timedelta(minutes=5)) == []

    tracker.retain({"child-2"})
    # child-1 comes back as new: the first refresh sets the baseline again
    assert tracker.update("child-1", _screen_time(TODAY, com_video=900), START + timedelta(minutes=10)) == []


def _sensor(recent_apps: list) -> FamilyLinkScreenTimeSensor:
    coordinator = SimpleNamespace(
        data={
            "children_data": [
                {
                    "child_id": "child-1",
                    "child_name": "Alex",
                    "apps": [{"packageName": "com.video", "title": "Video"}],
                    "screen_time": {"total_seconds": 120, "date": TODAY, "app_breakdown": {}},
                    "recent_apps": recent_apps,
                }
            ]
        },
        child_device_ids={},
        last_update_success=True,
    )
    return FamilyLinkScreenTimeSensor(coordinator, "total", child_id="child-1", child_name="Alex")


def test_the_sensor_names_the_recent_apps_and_keeps_them_out_of_the_recorder():
    recent = [{"package": "com.video", "device": "Pixel 9 Pro", "grew_minutes": 5.0, "today_minutes": 15.0, "reported_at": START.isoformat()}]

    assert _sensor(recent).extra_state_attributes["recent_apps"] == [{"name": "Video", **recent[0]}]
    assert "recent_apps" in FamilyLinkScreenTimeSensor._unrecorded_attributes


def test_the_sensor_adds_nothing_without_recent_apps():
    assert "recent_apps" not in _sensor([]).extra_state_attributes
