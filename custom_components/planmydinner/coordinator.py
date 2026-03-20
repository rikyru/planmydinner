"""DataUpdateCoordinator for Plan My Dinner."""
from __future__ import annotations
import logging
import os
from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL_MINUTES
from .api_client import PlanMyDinnerApiClient

_LOGGER = logging.getLogger(__name__)
# Try both slugs: locally installed add-ons use "local_<slug>", repo add-ons use the plain slug
_ADDON_SLUGS = ["local_planmydinner", "planmydinner"]


async def _fetch_ingress_path(hass: HomeAssistant) -> str | None:
    """Get the add-on ingress URL path from the HA Supervisor."""
    # Preferred: use HA's own hassio component API (no token needed)
    try:
        from homeassistant.components.hassio import async_get_addon_info
        for slug in _ADDON_SLUGS:
            try:
                info = await async_get_addon_info(hass, slug)
                url = info.get("ingress_url")
                if url:
                    _LOGGER.debug("Got ingress_url via hassio API for slug %s: %s", slug, url)
                    return url
            except Exception:
                continue
    except ImportError:
        pass

    # Fallback: direct HTTP call to supervisor
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        _LOGGER.warning("planmydinner: SUPERVISOR_TOKEN not set, cannot fetch ingress path")
        return None
    session = async_get_clientsession(hass)
    for slug in _ADDON_SLUGS:
        try:
            async with session.get(
                f"http://supervisor/addons/{slug}/info",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    url = data.get("data", {}).get("ingress_url")
                    if url:
                        _LOGGER.debug("Got ingress_url via HTTP for slug %s: %s", slug, url)
                        return url
                else:
                    _LOGGER.debug("Supervisor returned %s for slug %s", resp.status, slug)
        except Exception as e:
            _LOGGER.warning("planmydinner: supervisor HTTP call failed for slug %s: %s", slug, e)
    return None

def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class PlanMyDinnerCoordinator(DataUpdateCoordinator):
    """Fetches and caches Plan My Dinner data for all sensors."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: PlanMyDinnerApiClient,
        profile_id_A: str,
        profile_id_B: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.api_client = api_client
        self.profile_id_A = profile_id_A
        self.profile_id_B = profile_id_B

    async def _async_update_data(self) -> dict:
        """Fetch all data from the API."""
        today = date.today()
        monday = _get_monday(today)

        results = {}

        # Today's plan (read-only, no generation)
        try:
            results["today"] = await self.api_client.get_plan_for_date(
                self.profile_id_A, self.profile_id_B, today.isoformat()
            )
        except Exception as e:
            _LOGGER.warning("Could not fetch today's plan: %s", e)
            results["today"] = None

        # This week's stored plan
        try:
            results["week"] = await self.api_client.get_weekly_plan_stored(
                self.profile_id_A, self.profile_id_B, monday.isoformat()
            )
        except Exception as e:
            _LOGGER.warning("Could not fetch weekly plan: %s", e)
            results["week"] = None

        # Shopping list
        try:
            results["shopping"] = await self.api_client.get_shopping_list(
                self.profile_id_A, self.profile_id_B, monday.isoformat()
            )
        except Exception as e:
            _LOGGER.warning("Could not fetch shopping list: %s", e)
            results["shopping"] = None

        # Pantry
        try:
            results["pantry"] = await self.api_client.get_pantry_items()
        except Exception as e:
            _LOGGER.warning("Could not fetch pantry: %s", e)
            results["pantry"] = []

        # Ingress path for Lovelace card (via HA Supervisor — no add-on rebuild needed)
        if not hasattr(self, "_ingress_path"):
            self._ingress_path = await _fetch_ingress_path(self.hass)
        results["ingress_path"] = self._ingress_path

        return results
