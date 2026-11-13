"""App icons from Google's app list on the per-app usage attributes and the top app sensors."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.familylink.sensor import (
    FamilyLinkDeviceDailyScreenTimeSensor,
    FamilyLinkScreenTimeSensor,
    FamilyLinkTopAppSensor,
)

GAME_ICON = "https://lh3.googleusercontent.com/game-icon"


def _coordinator() -> SimpleNamespace:
    return SimpleNamespace(
        data={
            "children_data": [
                {
                    "child_id": "child-1",
                    "child_name": "Test Child",
                    "apps": [
                        {"packageName": "com.game", "title": "Game", "iconUrl": GAME_ICON},
                        {"packageName": "com.video", "title": "Video"},
                    ],
                    "screen_time": {
                        "total_seconds": 2400.0,
                        "formatted": "00:40:00",
                        "hours": 0,
                        "minutes": 40,
                        "seconds": 0,
                        "app_breakdown": {"com.game": 1800.0, "com.video": 600.0},
                        "device_screen_time": {
                            "dev-phone": {
                                "name": "Pixel 9 Pro",
                                "total_seconds": 2400.0,
                                "formatted": "00:40:00",
                                "minutes": 40.0,
                                "hours": 0,
                                "app_breakdown": {"com.game": 1800.0, "com.video": 600.0},
                            },
                        },
                    },
                }
            ]
        },
        child_device_ids={"child-1": "hub-device-1"},
        last_update_success=True,
    )


def test_child_apps_carry_the_icon_when_google_has_one():
    sensor = FamilyLinkScreenTimeSensor(_coordinator(), "total", child_id="child-1", child_name="Test Child")

    game, video = sensor.extra_state_attributes["apps"]
    assert game["icon_url"] == GAME_ICON
    assert "icon_url" not in video


def test_device_apps_carry_the_icon_when_google_has_one():
    sensor = FamilyLinkDeviceDailyScreenTimeSensor(
        _coordinator(),
        child_id="child-1",
        child_name="Test Child",
        device_id="dev-phone",
        device_name="Pixel 9 Pro",
    )

    game, video = sensor.extra_state_attributes["apps"]
    assert game == {"name": "Game", "package": "com.game", "time": "00:30:00", "minutes": 30.0, "icon_url": GAME_ICON}
    assert "icon_url" not in video


def test_top_app_sensor_shows_the_app_icon():
    coordinator = _coordinator()
    first = FamilyLinkTopAppSensor(coordinator, 1, child_id="child-1", child_name="Test Child")
    second = FamilyLinkTopAppSensor(coordinator, 2, child_id="child-1", child_name="Test Child")

    assert first.extra_state_attributes["icon_url"] == GAME_ICON
    assert first.entity_picture == GAME_ICON
    assert second.extra_state_attributes["icon_url"] is None
    assert second.entity_picture is None


def test_an_app_usage_sensor_shows_the_apps_icon():
    from custom_components.familylink.sensor import FamilyLinkAppUsageSensor

    coordinator = SimpleNamespace(
        data={
            "children_data": [
                {
                    "child_id": "1001",
                    "child_name": "Alex",
                    "apps": [{"packageName": "com.video", "title": "Video", "iconUrl": "https://example.com/video.png"}],
                    "screen_time": {"date": None, "app_breakdown": {"com.video": 60}},
                    "devices": [],
                }
            ]
        },
        child_device_ids={},
        last_update_success=True,
    )

    sensor = FamilyLinkAppUsageSensor(coordinator, "1001", "Alex", "com.video")

    assert sensor.entity_picture == "https://example.com/video.png"
    assert sensor.name == "Video usage today"
