"""
location/location_service.py
-----------------------------
Orchestrator for the Automatic Location Detection feature.

Responsibilities
----------------
1. Detect the coordinate format of the uploaded DataFrame (lat/lon vs projected).
2. For lat/lon files  → extract centroid directly.
3. For projected files → validate CRS, convert to lat/lon using pyproj.
4. Call the reverse geocoder with the centroid.
5. Build the Google Maps URL.
6. Return a single :class:`LocationResult` object to the UI.

Single responsibility: orchestration only.
Business logic lives in coordinate_converter.py and reverse_geocoder.py.
No Streamlit, no file I/O.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from config import GOOGLE_MAPS_URL_TEMPLATE
from location.coordinate_converter import (
    ConversionResult,
    CoordinateConversionError,
    InvalidCRSError,
    InvalidCoordinateRangeError,
    convert_dataframe_to_latlon,
    detect_coordinate_format,
    extract_latlon_from_dataframe,
)
from location.reverse_geocoder import (
    GeocodingResult,
    NetworkUnavailableError,
    ReverseGeocoderError,
    reverse_geocode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class LocationResult:
    """
    Complete outcome of the location detection pipeline.

    Attributes
    ----------
    coordinate_format:
        ``'latlon'`` or ``'projected'``.
    conversion:
        The result of coordinate extraction / conversion.  Always present
        when the pipeline succeeds.
    geocoding:
        The result of reverse geocoding.  ``None`` if geocoding failed or
        was skipped.
    google_maps_url:
        Direct Google Maps link for the centroid.  Empty string on failure.
    error:
        Human-readable description of any error that occurred.  Empty string
        when the pipeline succeeded completely.
    warnings:
        Non-fatal advisory messages (e.g. geocoding failed but conversion
        succeeded).
    """

    coordinate_format: str = ""
    conversion: ConversionResult | None = None
    geocoding: GeocodingResult | None = None
    google_maps_url: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def has_location(self) -> bool:
        """True when a valid centroid coordinate is available."""
        return self.conversion is not None

    @property
    def has_geocoding(self) -> bool:
        """True when reverse geocoding produced a result."""
        return self.geocoding is not None

    @property
    def succeeded(self) -> bool:
        """True when the pipeline completed without a fatal error."""
        return self.error == ""

    @property
    def latitude(self) -> float | None:
        """Centroid latitude, or None if unavailable."""
        return self.conversion.latitude if self.conversion else None

    @property
    def longitude(self) -> float | None:
        """Centroid longitude, or None if unavailable."""
        return self.conversion.longitude if self.conversion else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_location(
    df: pd.DataFrame,
    source_crs: str | None = None,
) -> LocationResult:
    """
    Run the full location detection pipeline on a survey DataFrame.

    Pipeline steps
    --------------
    1. Detect coordinate format (``'latlon'`` vs ``'projected'``).
    2. Extract or convert centroid to WGS84 lat/lon.
    3. Reverse-geocode the centroid.
    4. Build Google Maps URL.

    Parameters
    ----------
    df:
        Normalised survey DataFrame (output of ``data.reader.read_file``).
        May contain Easting/Northing, Latitude/Longitude, or both.
    source_crs:
        Required when the DataFrame uses projected coordinates.
        Ignored when the format is detected as ``'latlon'``.
        Example: ``'EPSG:32644'``.

    Returns
    -------
    LocationResult
        Always returned — never raises.  Check ``result.succeeded`` and
        ``result.error`` to determine whether the pipeline completed.

    Notes
    -----
    This function intentionally catches all exceptions and converts them
    to ``LocationResult.error`` messages.  The application must not crash
    due to a network failure or bad CRS input.
    """
    result = LocationResult()

    # ------------------------------------------------------------------
    # Step 1: Detect format
    # ------------------------------------------------------------------
    try:
        fmt = detect_coordinate_format(df)
        result.coordinate_format = fmt
    except Exception as exc:
        result.error = f"Could not detect coordinate format: {exc}"
        logger.exception("Format detection failed.")
        return result

    # ------------------------------------------------------------------
    # Step 2: Extract / convert to lat/lon
    # ------------------------------------------------------------------
    try:
        if fmt == "latlon":
            conversion = extract_latlon_from_dataframe(df)
        else:
            # Projected – CRS is mandatory
            if not source_crs:
                result.error = (
                    "This file uses Easting/Northing coordinates. "
                    "Please select the Coordinate Reference System (CRS) "
                    "to enable location detection."
                )
                return result
            conversion = convert_dataframe_to_latlon(df, source_crs)

        result.conversion = conversion
        result.google_maps_url = GOOGLE_MAPS_URL_TEMPLATE.format(
            lat=conversion.latitude, lon=conversion.longitude
        )

    except InvalidCRSError as exc:
        result.error = f"Invalid CRS: {exc}"
        logger.warning("CRS validation failed: %s", exc)
        return result

    except (CoordinateConversionError, InvalidCoordinateRangeError) as exc:
        result.error = f"Coordinate conversion failed: {exc}"
        logger.warning("Conversion failed: %s", exc)
        return result

    except Exception as exc:
        result.error = f"Unexpected error during coordinate processing: {exc}"
        logger.exception("Unexpected conversion error.")
        return result

    # ------------------------------------------------------------------
    # Step 3: Reverse geocode
    # ------------------------------------------------------------------
    try:
        geocoding = reverse_geocode(conversion.latitude, conversion.longitude)
        result.geocoding = geocoding

        logger.info(
            "Location pipeline complete: lat=%.6f, lon=%.6f, city=%r, country=%r.",
            conversion.latitude, conversion.longitude,
            geocoding.city, geocoding.country,
        )

    except NetworkUnavailableError as exc:
        # Geocoding failed but coordinates are valid – surface as warning
        result.warnings.append(
            f"Reverse geocoding unavailable: {exc} "
            "Coordinates are still available."
        )
        logger.warning("Geocoding network error: %s", exc)

    except ReverseGeocoderError as exc:
        result.warnings.append(
            f"Reverse geocoding returned no result: {exc}"
        )
        logger.warning("Geocoding returned no result: %s", exc)

    except Exception as exc:
        result.warnings.append(
            f"Unexpected geocoding error: {exc}"
        )
        logger.exception("Unexpected geocoding error.")

    return result
