"""
location/reverse_geocoder.py
-----------------------------
Responsible for reverse geocoding a (latitude, longitude) pair into a
structured place description using the Nominatim geocoder (OpenStreetMap).

Single responsibility: geocoding only.
No coordinate conversion, no UI, no file I/O.

Nominatim address keys observed in practice
--------------------------------------------
road, neighbourhood, suburb, city, state_district, state,
postcode, country, country_code, ISO3166-2-lvl4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from geopy.exc import (
    GeocoderServiceError,
    GeocoderTimedOut,
    GeocoderUnavailable,
)
from geopy.geocoders import Nominatim

from config import (
    GEOCODER_LANGUAGE,
    GEOCODER_TIMEOUT,
    GEOCODER_USER_AGENT,
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class ReverseGeocoderError(Exception):
    """Raised when the geocoder returns no result or a service error occurs."""


class NetworkUnavailableError(ReverseGeocoderError):
    """Raised when the network or geocoding service cannot be reached."""


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeocodingResult:
    """
    Structured place information returned by reverse geocoding.

    All string fields default to an empty string when the geocoder does
    not return data for that field — callers should always check before
    displaying.

    Attributes
    ----------
    latitude:
        The latitude used for the query (not necessarily the centroid of
        the returned place polygon).
    longitude:
        The longitude used for the query.
    display_name:
        Full human-readable address string from Nominatim.
    country:
        Country name.
    state:
        State or province name.
    state_district:
        District name (level below state).
    city:
        City, town, or municipality name.
    suburb:
        Suburb or neighbourhood name.
    postcode:
        Postal / PIN code.
    road:
        Nearest road or street name — used as the "nearest landmark"
        proxy when no explicit landmark is available.
    country_code:
        ISO 3166-1 alpha-2 country code, e.g. ``'in'``.
    raw:
        The complete raw Nominatim address dictionary for advanced use.
    """

    latitude: float
    longitude: float
    display_name: str = ""
    country: str = ""
    state: str = ""
    state_district: str = ""
    city: str = ""
    suburb: str = ""
    postcode: str = ""
    road: str = ""
    country_code: str = ""
    raw: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def nearest_landmark(self) -> str:
        """
        Best available nearby place descriptor.

        Priority: road > suburb > neighbourhood > city.
        Returns an empty string if none are available.
        """
        return self.road or self.suburb or self.city

    @property
    def google_maps_url(self) -> str:
        """
        Direct Google Maps link for these coordinates.
        Imported here for completeness; also built in location_service.py.
        """
        from config import GOOGLE_MAPS_URL_TEMPLATE
        return GOOGLE_MAPS_URL_TEMPLATE.format(lat=self.latitude, lon=self.longitude)

    def __str__(self) -> str:
        return (
            f"GeocodingResult("
            f"city={self.city!r}, state={self.state!r}, "
            f"country={self.country!r}, postcode={self.postcode!r})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_geocoder() -> Nominatim:
    """
    Instantiate a Nominatim geocoder with the configured user-agent.

    Returns
    -------
    geopy.geocoders.Nominatim
    """
    return Nominatim(user_agent=GEOCODER_USER_AGENT)


def _extract_address_fields(raw_location) -> GeocodingResult:
    """
    Parse a raw geopy ``Location`` object into a :class:`GeocodingResult`.

    Parameters
    ----------
    raw_location:
        The ``Location`` object returned by ``geolocator.reverse()``.

    Returns
    -------
    GeocodingResult
    """
    addr: dict = raw_location.raw.get("address", {})
    display: str = raw_location.raw.get("display_name", "")
    lat: float = float(raw_location.raw.get("lat", 0.0))
    lon: float = float(raw_location.raw.get("lon", 0.0))

    # Nominatim uses several keys for "city" depending on place type
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or ""
    )

    return GeocodingResult(
        latitude=lat,
        longitude=lon,
        display_name=display,
        country=addr.get("country", ""),
        state=addr.get("state", ""),
        state_district=addr.get("state_district", ""),
        city=city,
        suburb=addr.get("suburb") or addr.get("neighbourhood") or "",
        postcode=addr.get("postcode", ""),
        road=addr.get("road", ""),
        country_code=addr.get("country_code", "").upper(),
        raw=addr,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reverse_geocode(latitude: float, longitude: float) -> GeocodingResult:
    """
    Perform reverse geocoding for a geographic coordinate pair.

    Uses Nominatim (OpenStreetMap) — free, no API key required.

    Parameters
    ----------
    latitude:
        Decimal degrees, WGS84.  Must be in [-90, 90].
    longitude:
        Decimal degrees, WGS84.  Must be in [-180, 180].

    Returns
    -------
    GeocodingResult
        Structured place information.

    Raises
    ------
    ValueError
        If lat/lon are outside valid bounds.
    ReverseGeocoderError
        If Nominatim returns no result for the coordinate.
    NetworkUnavailableError
        If the network or Nominatim service cannot be reached.
    """
    # Bounds check
    if not (LATITUDE_MIN <= latitude <= LATITUDE_MAX):
        raise ValueError(
            f"Latitude {latitude} is outside [-90, 90]."
        )
    if not (LONGITUDE_MIN <= longitude <= LONGITUDE_MAX):
        raise ValueError(
            f"Longitude {longitude} is outside [-180, 180]."
        )

    geolocator = _build_geocoder()

    query = f"{latitude:.6f},{longitude:.6f}"
    logger.info("Reverse geocoding: %s", query)

    try:
        location = geolocator.reverse(
            query,
            language=GEOCODER_LANGUAGE,
            timeout=GEOCODER_TIMEOUT,
        )
    except GeocoderTimedOut as exc:
        raise NetworkUnavailableError(
            f"Geocoder timed out after {GEOCODER_TIMEOUT}s. "
            "Check your internet connection and try again."
        ) from exc
    except (GeocoderUnavailable, GeocoderServiceError) as exc:
        raise NetworkUnavailableError(
            f"Geocoding service unavailable: {exc}. "
            "Check your internet connection."
        ) from exc
    except Exception as exc:
        raise ReverseGeocoderError(
            f"Unexpected geocoder error: {exc}"
        ) from exc

    if location is None:
        raise ReverseGeocoderError(
            f"No place found for coordinates ({latitude:.6f}, {longitude:.6f}). "
            "The point may be in an ocean, uninhabited area, or outside "
            "Nominatim's coverage."
        )

    result = _extract_address_fields(location)

    logger.info(
        "Geocoding result: city=%r, state=%r, country=%r, postcode=%r.",
        result.city, result.state, result.country, result.postcode,
    )

    return result
