"""The Chrome filter mode select and the request that sets the mode."""

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


class _Response:
    def __init__(self, status: int, text: str = "") -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


def _client(status: int = 200) -> tuple[FamilyLinkClient, MagicMock]:
    client = object.__new__(FamilyLinkClient)
    session = MagicMock()
    session.post = MagicMock(return_value=_Response(status, "error"))
    client.is_authenticated = lambda: True
    client._get_session = AsyncMock(return_value=session)
    client._get_cookie_header = lambda: "SAPISID=x"
    return client, session


async def test_the_client_sends_the_mode_for_the_child_in_the_body() -> None:
    client, session = _client()

    await client.async_set_web_filter(CHILD, FamilyLinkClient.WEB_FILTER_APPROVED_ONLY)

    url = session.post.call_args.args[0]
    assert url == f"{FamilyLinkClient.BASE_URL}/people/settingResources:performAction"
    body = json.loads(session.post.call_args.kwargs["data"])
    assert body == [None, [[1, ["124", None, [CHILD]], "2"]], [[1, 3, 4, 5, 6], 1]]


async def test_the_client_raises_on_an_error_answer() -> None:
    client, _ = _client(status=400)

    with pytest.raises(Exception, match="HTTP 400"):
        await client.async_set_web_filter(CHILD, FamilyLinkClient.WEB_FILTER_BLOCK_EXPLICIT)


async def test_the_client_refuses_a_malformed_child_id() -> None:
    client, session = _client()

    with pytest.raises(Exception):
        await client.async_set_web_filter("123/../x", FamilyLinkClient.WEB_FILTER_BLOCK_EXPLICIT)
    session.post.assert_not_called()


def _coordinator(websites) -> SimpleNamespace:
    return SimpleNamespace(
        data={"children_data": [{"child_id": CHILD, "child_name": "Alex", "websites": websites}]},
        last_update_success=True,
        client=SimpleNamespace(async_set_web_filter=AsyncMock()),
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
        ("blockByDefault", "Only allow approved sites"),
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


async def test_choosing_an_option_sets_the_mode_and_keeps_it_with_the_lists() -> None:
    coordinator = _coordinator({"filter_level": "safeSites", "approved": ["a.example"], "blocked": []})
    select = FamilyLinkWebFilterSelect(coordinator, CHILD, "Alex")

    await select.async_select_option("Only allow approved sites")

    coordinator.client.async_set_web_filter.assert_awaited_once_with(CHILD, "2")
    # Not read back: Google can still answer with the previous mode
    coordinator.store_websites.assert_called_once_with(
        CHILD, {"filter_level": "blockByDefault", "approved": ["a.example"], "blocked": []}
    )
    coordinator.async_request_refresh.assert_awaited_once()


async def test_a_failed_change_raises_and_keeps_the_mode() -> None:
    coordinator = _coordinator({"filter_level": "safeSites"})
    coordinator.client.async_set_web_filter.side_effect = RuntimeError("HTTP 400")
    select = FamilyLinkWebFilterSelect(coordinator, CHILD, "Alex")

    with pytest.raises(HomeAssistantError, match="HTTP 400"):
        await select.async_select_option("Allow all sites")

    coordinator.store_websites.assert_not_called()
    coordinator.async_request_refresh.assert_not_called()
