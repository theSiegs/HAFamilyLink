"""The Chrome filter mode select: the all-sites mode and the mode just set."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import DOMAIN
from custom_components.familylink.select import FamilyLinkWebFilterSelect

CHILD = "123456789"


async def test_the_client_sends_all_sites_as_mode_one() -> None:
    client = object.__new__(FamilyLinkClient)
    session = MagicMock()

    class _Response:
        status = 200

        async def text(self) -> str:
            return "[]"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

    session.post = MagicMock(return_value=_Response())
    client.is_authenticated = lambda: True
    client._get_session = AsyncMock(return_value=session)
    client._get_cookie_header = lambda: "SAPISID=x"
    client.async_get_website_restrictions = AsyncMock(
        return_value={"filter_level": "allowByDefault", "approved": [], "blocked": []}
    )

    lists = await client.async_set_website_filter_level(CHILD, FamilyLinkClient.WEBSITE_FILTER_ALL_SITES)

    body = json.loads(session.post.call_args.kwargs["data"])
    assert body == [None, [[1, ["124", None, [CHILD]], "1"]], [[1, 3, 4, 5, 6], 1]]
    assert lists["filter_level"] == "allowByDefault"


def _coordinator(websites, read_back=None) -> SimpleNamespace:
    return SimpleNamespace(
        data={"children_data": [{"child_id": CHILD, "child_name": "Alex", "websites": websites}]},
        last_update_success=True,
        client=SimpleNamespace(async_set_website_filter_level=AsyncMock(return_value=read_back)),
        store_websites=MagicMock(),
        async_request_refresh=AsyncMock(),
    )


def test_the_select_shows_the_mode_read_with_the_site_lists() -> None:
    select = FamilyLinkWebFilterSelect(_coordinator({"filter_level": "safeSites"}), CHILD, "Alex")

    assert select.unique_id == f"{DOMAIN}_{CHILD}_web_filter"
    assert select.has_entity_name
    assert select.name == "Web Filter"
    assert select.available
    assert select.current_option == "Try to block explicit sites"
    assert select.extra_state_attributes == {"child_id": CHILD, "child_name": "Alex", "filter_level": "safeSites"}


@pytest.mark.parametrize(
    ("level", "option"),
    [
        ("allowByDefault", "Allow all sites"),
        ("safeSites", "Try to block explicit sites"),
        ("blockByDefault", "Only approved sites"),
    ],
)
def test_each_filter_level_google_returns_is_an_option(level, option) -> None:
    select = FamilyLinkWebFilterSelect(_coordinator({"filter_level": level}), CHILD, "Alex")

    assert select.current_option == option


def test_the_select_is_unavailable_until_the_site_lists_are_read() -> None:
    select = FamilyLinkWebFilterSelect(_coordinator(None), CHILD, "Alex")

    assert not select.available
    assert select.current_option is None


def test_an_unknown_filter_level_shows_no_option_but_stays_in_the_attributes() -> None:
    select = FamilyLinkWebFilterSelect(_coordinator({"filter_level": "somethingNew"}), CHILD, "Alex")

    assert select.current_option is None
    assert select.extra_state_attributes["filter_level"] == "somethingNew"


async def test_choosing_an_option_sets_the_mode_and_stores_the_lists_read_back() -> None:
    read_back = {"filter_level": "blockByDefault", "approved": ["a.example"], "blocked": []}
    coordinator = _coordinator({"filter_level": "safeSites", "approved": ["a.example"], "blocked": []}, read_back)
    select = FamilyLinkWebFilterSelect(coordinator, CHILD, "Alex")

    await select.async_select_option("Only approved sites")

    coordinator.client.async_set_website_filter_level.assert_awaited_once_with(CHILD, "approved_only")
    coordinator.store_websites.assert_called_once_with(CHILD, read_back)
    coordinator.async_request_refresh.assert_awaited_once()


async def test_a_stale_read_back_shows_the_mode_just_set() -> None:
    # Google can still answer with the previous mode right after a change
    read_back = {"filter_level": "safeSites", "approved": ["a.example"], "blocked": []}
    coordinator = _coordinator({"filter_level": "safeSites", "approved": ["a.example"], "blocked": []}, read_back)
    select = FamilyLinkWebFilterSelect(coordinator, CHILD, "Alex")

    await select.async_select_option("Allow all sites")

    coordinator.client.async_set_website_filter_level.assert_awaited_once_with(CHILD, "all_sites")
    coordinator.store_websites.assert_called_once_with(
        CHILD, {"filter_level": "allowByDefault", "approved": ["a.example"], "blocked": []}
    )


async def test_a_failed_change_raises_and_keeps_the_mode() -> None:
    coordinator = _coordinator({"filter_level": "safeSites"})
    coordinator.client.async_set_website_filter_level.side_effect = RuntimeError("HTTP 400")
    select = FamilyLinkWebFilterSelect(coordinator, CHILD, "Alex")

    with pytest.raises(HomeAssistantError, match="HTTP 400"):
        await select.async_select_option("Allow all sites")

    coordinator.store_websites.assert_not_called()
    coordinator.async_request_refresh.assert_not_called()
