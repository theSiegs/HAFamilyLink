"""Chrome site lists: patterns, the client's parsing of live responses, and the site services.

Response shapes below are the ones captured live on 2026-10-10 from
websites:listRestrictions / websites:updateRestrictions.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import DOMAIN
from custom_components.familylink.website_services import async_setup_website_services
from custom_components.familylink.websites import domain_patterns, normalize_site, parse_site_list

CHILD = "child-1"
LIST_URL = "https://lists.example.org/gaps.txt"

LIVE_LIST = {
    "filterLevel": "safeSites",
    "explicitWebsiteExceptions": [
        {"pattern": "*.example.*", "exceptionType": "block", "iconUrl": "https://encrypted-tbn2.gstatic.com/x"},
        {"pattern": "https://example.org/path?q=1", "exceptionType": "block"},
        {"pattern": "*.wikipedia.*", "exceptionType": "allow"},
    ],
}
LIVE_COVERED = {
    "filterLevel": "safeSites",
    "explicitWebsiteExceptions": [{"pattern": "*.example.*", "exceptionType": "block"}],
    "filteredExceptions": [
        {
            "exception": {"pattern": "example.net", "exceptionType": "block"},
            "coveredByException": {"pattern": "*.example.*", "exceptionType": "block"},
        }
    ],
}


# --- patterns -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("www.Example.com", "www.example.com"),
        ("  example.com/ ", "example.com"),
        ("*.example.com", "*.example.com"),
        ("*.example.*", "*.example.*"),
        ("https://example.com", "example.com"),
        ("https://example.org/path?q=1", "https://example.org/path?q=1"),
    ],
)
def test_normalize_site_accepts_the_documented_forms(value, expected) -> None:
    assert normalize_site(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "ex*ample.com", "*example.com", "example", "a" * 64 + ".com", "ftp://example.com/x", "exa mple.com", "*.*"],
)
def test_normalize_site_rejects_what_google_would_store_blindly(value) -> None:
    with pytest.raises(ValueError):
        normalize_site(value)


def test_domain_patterns_cover_the_domain_and_its_subdomains() -> None:
    assert domain_patterns("Example.com") == ["*.example.com", "example.com"]
    assert domain_patterns("*.example.*") == ["*.example.*"]


def test_parse_site_list_reads_comments_hosts_lines_and_skips_junk() -> None:
    text = "# header\nexample.com\n0.0.0.0 tracker.example.net  # hosts style\nexample.com\nnot a domain!\n\n"
    assert parse_site_list(text) == ["example.com", "tracker.example.net"]


# --- client parsing of live shapes ------------------------------------------------


def test_client_reads_the_lists_and_lowercase_types() -> None:
    lists = FamilyLinkClient._website_lists(LIVE_LIST)

    assert lists == {
        "filter_level": "safeSites",
        "approved": ["*.wikipedia.*"],
        "blocked": ["*.example.*", "https://example.org/path?q=1"],
    }


def test_client_reads_an_empty_list() -> None:
    assert FamilyLinkClient._website_lists({"filterLevel": "safeSites"}) == {
        "filter_level": "safeSites",
        "approved": [],
        "blocked": [],
    }


async def test_client_update_reports_covered_entries_without_listing_them() -> None:
    client = object.__new__(FamilyLinkClient)
    client._website_request = AsyncMock(return_value=LIVE_COVERED)

    result = await client.async_update_website_restrictions(CHILD, insert=[("example.net", "BLOCK")])

    method, child, suffix, body = client._website_request.await_args.args
    assert (method, child, suffix) == ("POST", CHILD, "websites:updateRestrictions")
    assert body["insertedWebsiteExceptions"] == [{"pattern": "example.net", "exceptionType": "BLOCK"}]
    assert result["blocked"] == ["*.example.*"]
    assert result["covered"] == {"example.net": "*.example.*"}


# --- services ---------------------------------------------------------------------


@pytest.fixture
async def site_services(hass):
    client = SimpleNamespace(
        async_get_website_restrictions=AsyncMock(
            return_value={"filter_level": "safeSites", "approved": ["*.wikipedia.*"], "blocked": ["manual.example"]}
        ),
        async_update_website_restrictions=AsyncMock(
            return_value={"filter_level": "safeSites", "approved": [], "blocked": [], "covered": {}}
        ),
    )
    coordinator = SimpleNamespace(client=client, store_websites=MagicMock(), async_request_refresh=AsyncMock())
    await async_setup_website_services(hass, coordinator)
    return coordinator


async def _call(hass, service, data):
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=True)


async def test_get_sites_returns_the_lists(hass, site_services) -> None:
    result = await _call(hass, "get_sites", {"child_id": CHILD})

    assert result["blocked"] == ["manual.example"]
    assert result["approved"] == ["*.wikipedia.*"]


async def test_block_and_allow_send_normalised_patterns(hass, site_services) -> None:
    update = site_services.client.async_update_website_restrictions

    await _call(hass, "block_site", {"child_id": CHILD, "sites": ["WWW.Example.com", "https://example.com"]})
    await _call(hass, "allow_site", {"child_id": CHILD, "sites": ["*.wikipedia.*"]})

    assert update.await_args_list[0].kwargs["insert"] == [("www.example.com", "BLOCK"), ("example.com", "BLOCK")]
    assert update.await_args_list[1].kwargs["insert"] == [("*.wikipedia.*", "ALLOW")]
    assert site_services.store_websites.call_count == 2


async def test_an_invalid_site_raises_before_any_write(hass, site_services) -> None:
    with pytest.raises(ServiceValidationError, match="Wildcards"):
        await _call(hass, "block_site", {"child_id": CHILD, "sites": ["ex*ample.com"]})

    site_services.client.async_update_website_restrictions.assert_not_called()


async def test_a_site_service_needs_a_child(hass, site_services) -> None:
    with pytest.raises(ServiceValidationError, match="No child given"):
        await _call(hass, "block_site", {"sites": ["example.com"]})


async def test_remove_site_removes_manual_entries_with_their_type(hass, site_services) -> None:
    result = await _call(hass, "remove_site", {"child_id": CHILD, "sites": ["manual.example", "*.wikipedia.*", "other.example"]})

    remove = site_services.client.async_update_website_restrictions.await_args.kwargs["remove"]
    assert remove == [("manual.example", "BLOCK"), ("*.wikipedia.*", "ALLOW")]
    assert result["not_listed"] == ["other.example"]


async def test_sync_adds_new_domains_and_removes_only_what_it_pushed(hass, site_services, aioclient_mock) -> None:
    update = site_services.client.async_update_website_restrictions
    lists = site_services.client.async_get_website_restrictions

    # First sync: a and b are new; the manual entry and the approved site are left alone
    aioclient_mock.get(LIST_URL, text="# list\na.example\nb.example\nwikipedia.org\n")
    lists.return_value = {"filter_level": "safeSites", "approved": ["*.wikipedia.org"], "blocked": ["manual.example"]}
    first = await _call(hass, "sync_site_list", {"child_id": CHILD, "url": LIST_URL})

    inserted = [p for p, _ in update.await_args.kwargs["insert"]]
    # wikipedia.org is skipped whole: blocking it would beat the approved *.wikipedia.org
    assert inserted == ["*.a.example", "a.example", "*.b.example", "b.example"]
    assert update.await_args.kwargs["remove"] == []
    assert first["skipped_approved"] == ["wikipedia.org"]

    # Second sync: b dropped from the list; it is removed, the manual entry is not
    aioclient_mock.clear_requests()
    aioclient_mock.get(LIST_URL, text="a.example\nwikipedia.org\n")
    lists.return_value = {
        "filter_level": "safeSites",
        "approved": ["*.wikipedia.org"],
        "blocked": ["manual.example", "*.a.example", "a.example", "*.b.example", "b.example"],
    }
    second = await _call(hass, "sync_site_list", {"child_id": CHILD, "url": LIST_URL})

    assert update.await_args.kwargs["insert"] == []
    assert sorted(p for p, _ in update.await_args.kwargs["remove"]) == ["*.b.example", "b.example"]
    assert second["removed"] == ["*.b.example", "b.example"]
    assert second["removed_count"] == 2


async def test_sync_refuses_a_list_over_the_cap(hass, site_services, aioclient_mock) -> None:
    aioclient_mock.get(LIST_URL, text="\n".join(f"d{i}.example" for i in range(5)))

    with pytest.raises(HomeAssistantError, match="more than max_domains"):
        await _call(hass, "sync_site_list", {"child_id": CHILD, "url": LIST_URL, "max_domains": 3})

    site_services.client.async_update_website_restrictions.assert_not_called()


async def test_sync_stop_removes_what_the_list_added_and_forgets_it(hass, site_services, aioclient_mock) -> None:
    update = site_services.client.async_update_website_restrictions
    lists = site_services.client.async_get_website_restrictions
    aioclient_mock.get(LIST_URL, text="a.example\n")
    lists.return_value = {"filter_level": "safeSites", "approved": [], "blocked": ["manual.example"]}
    await _call(hass, "sync_site_list", {"child_id": CHILD, "url": LIST_URL})

    lists.return_value = {"filter_level": "safeSites", "approved": [], "blocked": ["manual.example", "*.a.example", "a.example"]}
    stopped = await _call(hass, "sync_site_list", {"child_id": CHILD, "url": LIST_URL, "stop": True})

    assert sorted(p for p, _ in update.await_args.kwargs["remove"]) == ["*.a.example", "a.example"]
    assert stopped["removed_count"] == 2
    # Forgotten: a second stop has nothing to remove and makes no call
    calls = update.await_count
    again = await _call(hass, "sync_site_list", {"child_id": CHILD, "url": LIST_URL, "stop": True})
    assert again["removed_count"] == 0
    assert update.await_count == calls

