"""Apps whose usage grew recently, from Google's daily totals.

Google has no session times, only a daily total per app and device, and a
device uploads its usage in batches (about every 5 minutes for a phone in use,
15 to 20 for a tablet). So this reports what was measured, not what the child
was doing: an app whose total grew between two refreshes, by how much, and when
Google received it (the use itself happened before that).

The first refresh of a day, or after a restart, only sets the baseline: what
grew while Home Assistant was not looking is not known.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# An app stays listed this long after growth was last seen for it
RECENT_USAGE_WINDOW = timedelta(minutes=30)

_Key = tuple[str, str]  # (package, device id)


class RecentUsageTracker:
	"""Remembers each child's last totals to see which apps grew since."""

	def __init__(self, window: timedelta = RECENT_USAGE_WINDOW) -> None:
		self._window = window
		self._seen: dict[str, tuple[Any, dict[_Key, float]]] = {}  # child -> (day, seconds per key)
		# child -> key -> (seen at, received by Google at, seconds grown)
		self._grew: dict[str, dict[_Key, tuple[datetime, datetime, float]]] = {}

	def update(self, child_id: str, screen_time: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
		"""Record this refresh and return the apps that grew within the window, newest first."""
		if not screen_time:
			return []
		day = screen_time.get("date")
		seen_day, seen = self._seen.get(child_id, (None, {}))
		grew = self._grew.setdefault(child_id, {})
		# When Google received the usage; never later than now
		received = min(now, _received_at(screen_time.get("data_refreshed_ms")) or now)

		current: dict[_Key, float] = {}
		for item in screen_time.get("app_device_usage") or []:
			key = (item.get("package"), item.get("device_id"))
			current[key] = item.get("seconds") or 0
			delta = current[key] - seen.get(key, 0)
			if seen_day == day and delta > 1:
				previous = grew.get(key)
				# Growth still inside the window adds up; an older one starts over
				if previous and now - previous[0] <= self._window:
					delta += previous[2]
				grew[key] = (now, received, delta)
		self._seen[child_id] = (day, current)

		for key in [k for k, (seen_at, _, _) in grew.items() if now - seen_at > self._window]:
			del grew[key]
		devices = screen_time.get("device_names") or {}
		recent = [
			{
				"package": package,
				"device": devices.get(device, device),
				"grew_minutes": round(seconds / 60, 1),
				"today_minutes": round(current.get((package, device), 0) / 60, 1),
				"reported_at": when.isoformat(),
			}
			for (package, device), (_, when, seconds) in sorted(grew.items(), key=lambda item: item[1][0], reverse=True)
		]
		return recent

	def retain(self, child_ids: set[str]) -> None:
		"""Forget children that are no longer in the family."""
		for known in (self._seen, self._grew):
			for child_id in [c for c in known if c not in child_ids]:
				del known[child_id]


def _received_at(millis: Any) -> datetime | None:
	"""Google's "usage received" time (epoch milliseconds), None when absent or unreadable."""
	try:
		return datetime.fromtimestamp(int(millis) / 1000, timezone.utc)
	except (TypeError, ValueError, OverflowError, OSError):
		return None
