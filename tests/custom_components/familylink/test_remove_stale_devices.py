"""A device Google no longer lists can be deleted from Home Assistant.

A reset or replaced phone, or an emulator used once, stays in the device
registry with unavailable entities. Home Assistant offers Delete only when the
integration agrees; a device still listed would come back on the next refresh.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.familylink import async_remove_config_entry_device
from custom_components.familylink.const import DOMAIN

ENTRY = SimpleNamespace(entry_id="entry-1")
DATA = {
    "children_data": [
        {"child_id": "1001", "devices": [{"id": "phone"}, {"id": "tv"}]},
    ]
}


def _hass(data):
    coordinator = SimpleNamespace(data=data)
    return SimpleNamespace(data={DOMAIN: {ENTRY.entry_id: coordinator}})


def _device(*identifiers):
    return SimpleNamespace(identifiers={(DOMAIN, identifier) for identifier in identifiers})


async def test_a_device_google_no_longer_lists_can_be_deleted() -> None:
    assert await async_remove_config_entry_device(_hass(DATA), ENTRY, _device("1001_old-emulator"))


async def test_a_listed_device_stays() -> None:
    assert not await async_remove_config_entry_device(_hass(DATA), ENTRY, _device("1001_phone"))


async def test_a_childs_hub_stays() -> None:
    assert not await async_remove_config_entry_device(_hass(DATA), ENTRY, _device("1001"))


async def test_the_same_device_under_another_child_can_be_deleted() -> None:
    # Each child has its own copy of a shared device; only listed copies stay
    assert await async_remove_config_entry_device(_hass(DATA), ENTRY, _device("1002_tv"))


async def test_nothing_is_deleted_before_the_first_data() -> None:
    assert not await async_remove_config_entry_device(_hass(None), ENTRY, _device("1001_old-emulator"))
    assert not await async_remove_config_entry_device(
        SimpleNamespace(data={}), ENTRY, _device("1001_old-emulator")
    )
