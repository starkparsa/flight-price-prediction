"""
⚠️ DEAD CODE as of 2026-09-05: Amadeus decommissioned its self-service
developer portal on 2026-07-17. This module can no longer be used — there
is no way to obtain AMADEUS_CLIENT_ID/SECRET anymore. Kept for reference
(the OAuth2/never-raises/tiny-.env-loader pattern is reusable against
whatever provider replaces it) — see decisions.md's pivot entry and
STATUS.md before touching this file or collect_fares.py again.

Thin wrapper around the Amadeus Self-Service Flight Offers Search API.

Deliberately plain `requests` + OAuth2 client-credentials, not the official
`amadeus` SDK — zero extra install risk, full control over test vs
production host, consistent with this repo's other "no unnecessary
dependencies under time pressure" calls (see decisions.md).

Follows Itinera's own tool-function convention (see its backend/app/tools.py):
public methods never raise — they return a dict, and failures come back as
{"error": "..."} instead of an exception, so a caller (this repo's collector,
or eventually Itinera itself) can always safely inspect the result.

Credentials: set AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET, either as real
environment variables or in a local `.env` file (see `.env.example`).
Never commit real credentials — `.env` is gitignored.

Environment: AMADEUS_ENV=production (default) or =test.
  - production: real current prices, 2,000 free calls/month, then billed.
    quota_tracker.py enforces a conservative local cap so this never
    surprises anyone with a bill (see decisions.md).
  - test: Amadeus's scaled-down test data collection. Free/unlimited, but
    narrower airline/route coverage and not fully representative of live
    prices. Useful for developing/debugging this script without touching
    the production quota.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

_ENV_FILE = Path(__file__).parent / ".env"


def _load_dotenv() -> None:
    """Tiny .env loader — avoids adding python-dotenv as a dependency.
    Does not override variables already set in the real environment."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()

_HOSTS = {
    "production": "https://api.amadeus.com",
    "test": "https://test.api.amadeus.com",
}


class AmadeusError(Exception):
    """Internal only — callers never see this; public methods catch it and
    return {"error": ...} instead. Kept as a real exception type internally
    so the retry/token logic reads normally."""


class AmadeusClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 env: str | None = None):
        self.client_id = client_id or os.environ.get("AMADEUS_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("AMADEUS_CLIENT_SECRET")
        self.env = env or os.environ.get("AMADEUS_ENV", "production")
        if self.env not in _HOSTS:
            raise AmadeusError(f"AMADEUS_ENV must be 'production' or 'test', got {self.env!r}")
        self.base_url = _HOSTS[self.env]
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        if not self.client_id or not self.client_secret:
            raise AmadeusError(
                "Missing AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET. "
                "Sign up free at https://developers.amadeus.com, create an app, "
                "and put the keys in a local .env file (see .env.example)."
            )
        resp = requests.post(
            f"{self.base_url}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise AmadeusError(f"auth failed ({resp.status_code}): {resp.text[:300]}")
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 1799)
        return self._token

    def search_flight_offers(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        currency: str = "USD",
        max_results: int = 5,
    ) -> dict:
        """Returns {"offers": [...]} on success, {"error": "..."} on any
        failure (bad route, no availability, quota exceeded upstream, network
        error) — never raises. Each offer: price, currency, airline, stops
        (max stops across outbound+inbound), duration_minutes."""
        try:
            token = self._get_token()
        except AmadeusError as e:
            return {"error": str(e)}

        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": adults,
            "currencyCode": currency,
            "max": max_results,
        }
        if return_date:
            params["returnDate"] = return_date

        try:
            resp = requests.get(
                f"{self.base_url}/v2/shopping/flight-offers",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=20,
            )
        except requests.RequestException as e:
            return {"error": f"network error: {e}"}

        if resp.status_code != 200:
            return {"error": f"amadeus {resp.status_code}: {resp.text[:300]}"}

        try:
            data = resp.json().get("data", [])
        except ValueError:
            return {"error": "amadeus returned non-JSON response"}

        offers = []
        for offer in data:
            try:
                price = float(offer["price"]["total"])
                itineraries = offer["itineraries"]
                stops = max(len(it["segments"]) - 1 for it in itineraries)
                duration_minutes = None  # not parsed; ISO8601 duration in itineraries[i]["duration"] if needed later
                validating_airlines = offer.get("validatingAirlineCodes", [])
                airline = validating_airlines[0] if validating_airlines else None
                offers.append({
                    "price": price,
                    "currency": offer["price"].get("currency", currency),
                    "airline": airline,
                    "stops": stops,
                })
            except (KeyError, IndexError, ValueError, TypeError):
                continue  # skip malformed offer rather than fail the whole call

        return {"offers": offers}
