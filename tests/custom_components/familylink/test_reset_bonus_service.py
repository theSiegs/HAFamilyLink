"""familylink.reset_bonus ends the bonuses of one device, as its Reset Bonus button does."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.familylink import async_setup_services
from custom_components.familylink.const import DOMAIN

CHILD = "child-1"
PHONE = "device-phone"
BONUS_SENSOR = "sensor.phone_active_bonus"
RESET_BUTTON = "button.phone_reset_bonus"


@pytest.fixture
async def services(hass, coordinator):
    coordinator.data = {"children_data": [{"child_id": CHILD, "devices": [{"id": PHONE}]}]}
    await async_setup_services(hass, coordinator)
    return coordinator


async def _call(hass, data: dict) -> dict:
    return await hass.services.async_call(DOMAIN, "reset_bonus", data, blocking=True, return_response=True)


async def test_reset_bonus_by_device_and_child(hass, services) -> None:
    result = await _call(hass, {"device_id": PHONE, "child_id": CHILD})

    services.async_reset_bonus.assert_awaited_once_with(CHILD, PHONE)
    assert result == {"child_id": CHILD, "device_id": PHONE, "cancelled": 1}


async def test_reset_bonus_finds_the_child_of_a_known_device(hass, services) -> None:
    await _call(hass, {"device_id": PHONE})

    services.async_reset_bonus.assert_awaited_once_with(CHILD, PHONE)


async def test_reset_bonus_by_an_entity_with_device_attributes(hass, services) -> None:
    hass.states.async_set(BONUS_SENSOR, "30", {"device_id": PHONE, "child_id": CHILD})

    await _call(hass, {"entity_id": BONUS_SENSOR})

    services.async_reset_bonus.assert_awaited_once_with(CHILD, PHONE)


async def test_reset_bonus_by_the_reset_button_of_the_device(hass, services) -> None:
    """The button has no attributes: the device comes from the registry."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{CHILD}_{PHONE}")}
    )
    er.async_get(hass).async_get_or_create(
        "button", DOMAIN, f"{CHILD}_{PHONE}_reset_bonus", suggested_object_id="phone_reset_bonus", device_id=device.id
    )
    hass.states.async_set(RESET_BUTTON, "unknown", {})

    await _call(hass, {"entity_id": RESET_BUTTON})

    services.async_reset_bonus.assert_awaited_once_with(CHILD, PHONE)


async def test_reset_bonus_needs_a_device(hass, services) -> None:
    with pytest.raises(ServiceValidationError, match="No device given"):
        await _call(hass, {"child_id": CHILD})

    services.async_reset_bonus.assert_not_awaited()
