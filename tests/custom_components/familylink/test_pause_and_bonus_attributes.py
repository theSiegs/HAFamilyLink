"""What a consumer such as a screen-time manager reads back: paused apps, bonuses, per-device identity."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.familylink.binary_sensor import DailyLimitReachedBinarySensor
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator
from custom_components.familylink.sensor import (
    ActiveBonusSensor,
    DailyLimitDeviceSensor,
    FamilyLinkAppsWithLimitsSensor,
    ScreenTimeRemainingSensor,
)

CHILD = "child-1"
PHONE = "device-phone"
CHROME = "com.android.chrome"
GAME = "com.example.game"
VIDEO = "com.example.video"
GRANTED_MS = 1_790_000_000_000


def _coordinator(time_data: dict | None = None, apps: list | None = None, paused: dict | None = None):
    child = {"child_id": CHILD, "apps": apps or [], "devices_time_data": {PHONE: time_data} if time_data else {}}
    return SimpleNamespace(data={"children_data": [child]}, last_update_success=True, paused_apps=paused or {})


def _limit(package: str, minutes: int) -> dict:
    return {"packageName": package, "title": package, "supervisionSetting": {"usageLimit": {"dailyUsageLimitMins": minutes, "enabled": True}}}


def test_apps_with_limits_lists_the_apps_pause_app_paused() -> None:
    apps = [
        _limit(CHROME, 1),  # still at the pause limit
        _limit(GAME, 30),  # a parent changed it since the pause
        {"packageName": VIDEO, "supervisionSetting": {"alwaysAllowedAppInfo": {"alwaysAllowedState": "alwaysAllowedStateEnabled"}}},
    ]
    coordinator = _coordinator(apps=apps, paused={CHILD: {CHROME: 45, GAME: -1, VIDEO: 20}, "child-2": {CHROME: 5}})
    sensor = FamilyLinkAppsWithLimitsSensor(coordinator, child_id=CHILD, child_name="Alex")

    assert sensor.extra_state_attributes["paused_apps"] == [
        {"package": CHROME, "pause_intact": True, "prior": 45},
        {"package": GAME, "pause_intact": False, "prior": -1},
        # Made unlimited by a parent: no longer in the app list, still reported
        {"package": VIDEO, "pause_intact": False, "prior": 20},
    ]


def test_apps_with_limits_has_an_empty_paused_list_without_pauses() -> None:
    sensor = FamilyLinkAppsWithLimitsSensor(_coordinator(apps=[_limit(CHROME, 45)]), child_id=CHILD, child_name="Alex")

    assert sensor.extra_state_attributes["paused_apps"] == []


def test_active_bonus_shows_when_the_bonus_was_granted() -> None:
    coordinator = _coordinator({"bonus_minutes": 30, "bonus_override_id": "b-1", "bonus_granted_ms": GRANTED_MS})
    sensor = ActiveBonusSensor(coordinator, CHILD, "Alex", PHONE, "Phone")

    attributes = sensor.extra_state_attributes
    assert sensor.native_value == 30
    assert attributes["has_bonus"] is True
    granted = datetime.fromisoformat(attributes["bonus_granted_at"])
    assert granted == dt_util.utc_from_timestamp(GRANTED_MS / 1000)
    # Local time, as the other time attributes
    assert attributes["bonus_granted_at"] == dt_util.as_local(granted).isoformat()


def test_active_bonus_without_a_bonus_has_no_grant_time() -> None:
    sensor = ActiveBonusSensor(_coordinator({"bonus_minutes": 0, "bonus_granted_ms": None}), CHILD, "Alex", PHONE, "Phone")

    assert sensor.extra_state_attributes["has_bonus"] is False
    assert sensor.extra_state_attributes["bonus_granted_at"] is None


@pytest.mark.parametrize("time_data", [{"daily_limit_enabled": True, "daily_limit_minutes": 60}, None])
def test_per_device_entities_carry_the_child_and_device(time_data) -> None:
    coordinator = _coordinator(time_data)
    entities = [
        DailyLimitDeviceSensor(coordinator, CHILD, "Alex", PHONE, "Phone"),
        ScreenTimeRemainingSensor(coordinator, CHILD, "Alex", PHONE, "Phone"),
        ActiveBonusSensor(coordinator, CHILD, "Alex", PHONE, "Phone"),
        DailyLimitReachedBinarySensor(coordinator, PHONE, "Phone", {}, CHILD, "Alex"),
    ]
    for entity in entities:
        attributes = entity.extra_state_attributes
        assert attributes["child_id"] == CHILD, type(entity).__name__
        assert attributes["device_name"] == "Phone", type(entity).__name__
        assert attributes["device_id"] == PHONE, type(entity).__name__


class _Response:
    def __init__(self, body) -> None:
        self.status = 200
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def json(self):
        return self._body


def _applied_limits(override: list | None) -> list:
    device = [None] * 26
    device[0] = override
    device[25] = PHONE
    return [None, [device]]


def _bonus_override(created: str, seconds: str) -> list:
    """A bonus as the Family Link app or add_time_bonus posts it (Android shape, type 10)."""
    override = [None] * 14
    override[0], override[1], override[2], override[3] = "bonus-1", created, 10, PHONE
    override[13] = [[seconds, 0]]
    return override


async def _parse(body) -> dict:
    client = FamilyLinkClient.__new__(FamilyLinkClient)
    client.is_authenticated = MagicMock(return_value=True)
    client._get_cookie_header = MagicMock(return_value="SID=x")
    session = MagicMock()
    session.get = MagicMock(return_value=_Response(body))
    client._get_session = AsyncMock(return_value=session)
    return (await client.async_get_applied_time_limits(account_id=CHILD))["devices"][PHONE]


async def test_any_bonus_on_the_device_is_read_with_its_grant_time() -> None:
    """Whoever granted it (this integration or the Family Link app), the override is the same."""
    device = await _parse(_applied_limits(_bonus_override(str(GRANTED_MS), "1800")))

    assert device["bonus_minutes"] == 30
    assert device["bonus_override_id"] == "bonus-1"
    assert device["bonus_granted_ms"] == GRANTED_MS


async def test_no_bonus_no_grant_time() -> None:
    device = await _parse(_applied_limits(None))

    assert device["bonus_minutes"] == 0
    assert device["bonus_granted_ms"] is None


def _reset_coordinator(override_id: str | None, cancelled: int, single_ok: bool = True):
    coordinator = FamilyLinkDataUpdateCoordinator.__new__(FamilyLinkDataUpdateCoordinator)
    coordinator.client = SimpleNamespace(
        async_cancel_all_time_bonuses=AsyncMock(return_value=cancelled),
        async_cancel_time_bonus=AsyncMock(return_value=single_ok),
    )
    coordinator.data = _coordinator({"bonus_override_id": override_id}).data
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


async def test_reset_bonus_cancels_every_bonus_of_the_day() -> None:
    coordinator = _reset_coordinator("b-2", cancelled=2)

    assert await coordinator.async_reset_bonus(CHILD, PHONE) == 2

    coordinator.client.async_cancel_all_time_bonuses.assert_awaited_once_with(device_id=PHONE, account_id=CHILD)
    coordinator.client.async_cancel_time_bonus.assert_not_awaited()
    coordinator.async_request_refresh.assert_awaited_once()


async def test_reset_bonus_falls_back_to_the_reported_bonus() -> None:
    coordinator = _reset_coordinator("b-2", cancelled=0)

    assert await coordinator.async_reset_bonus(CHILD, PHONE) == 1

    coordinator.client.async_cancel_time_bonus.assert_awaited_once_with(override_id="b-2", account_id=CHILD)


async def test_reset_bonus_raises_when_the_reported_bonus_stays() -> None:
    coordinator = _reset_coordinator("b-2", cancelled=0, single_ok=False)

    with pytest.raises(HomeAssistantError):
        await coordinator.async_reset_bonus(CHILD, PHONE)


async def test_reset_bonus_without_a_bonus_is_zero() -> None:
    coordinator = _reset_coordinator(None, cancelled=0)

    assert await coordinator.async_reset_bonus(CHILD, PHONE) == 0
