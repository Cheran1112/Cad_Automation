"""
location/coordinate_converter.py
---------------------------------
Responsible for:
  1. Detecting whether a DataFrame carries geographic coordinates
     (Latitude/Longitude) or projected coordinates (Easting/Northing).
  2. Validating the chosen CRS string.
  3. Converting projected (Easting, Northing) to geographic
     (Latitude, Longitude) using pyproj.
  4. Computing the survey centroid in geographic coordinates.

Single responsibility: coordinate-space concerns only.
No geocoding, no UI, no file I/O.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

from config import (
    COL_EASTING,
    COL_LATITUDE,
    COL_LONGITUDE,
    COL_NORTHING,
    LATLON_ALIASES,
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
    TARGET_CRS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class InvalidCRSError(Exception):
    """Raised when the supplied CRS string cannot be parsed by pyproj."""


class CoordinateConversionError(Exception):
    """Raised when a projected → geographic transformation fails."""


class InvalidCoordinateRangeError(Exception):
    """Raised when converted lat/lon values fall outside valid bounds."""


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConversionResult:
    """
    The outcome of a coordinate conversion or detection operation.

    Attributes
    ----------
    latitude:
        Centroid latitude in decimal degrees (WGS84).
    longitude:
        Centroid longitude in decimal degrees (WGS84).
    source_crs:
        The CRS the coordinates were converted *from*, e.g. ``'EPSG:32644'``.
        ``'EPSG:4326'`` when the file already contained lat/lon.
    point_count:
        Number of survey points used to compute the centroid.
    was_converted:
        ``True`` when a pyproj transformation was performed;
        ``False`` when lat/lon were read directly from the file.
    """

    latitude: float
    longitude: float
    source_crs: str
    point_count: int
    was_converted: bool

    def __str__(self) -> str:
        action = "converted from" if self.was_converted else "read as"
        return (
            f"Centroid lat={self.latitude:.6f}, lon={self.longitude:.6f} "
            f"({action} {self.source_crs}, n={self.point_count})"
        )


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_coordinate_format(df: pd.DataFrame) -> str:
    """
    Inspect column names to determine which coordinate format the file uses.

    Parameters
    ----------
    df:
        Normalised survey DataFrame (after ``data.reader.read_file``).

    Returns
    -------
    str
        ``'latlon'`` if the DataFrame already contains Latitude/Longitude
        columns (via LATLON_ALIASES or exact names).

        ``'projected'`` if only Easting/Northing are present.

    Notes
    -----
    Detection is case-insensitive and covers all aliases defined in
    ``config.LATLON_ALIASES``.
    """
    alias_lower: dict[str, str] = {k.lower(): v for k, v in LATLON_ALIASES.items()}

    found: set[str] = set()
    for col in df.columns:
        canonical = alias_lower.get(col.strip().lower())
        if canonical in (COL_LATITUDE, COL_LONGITUDE):
            found.add(canonical)

    if COL_LATITUDE in found and COL_LONGITUDE in found:
        logger.info("Coordinate format detected: lat/lon (geographic).")
        return "latlon"

    logger.info("Coordinate format detected: Easting/Northing (projected).")
    return "projected"


# ---------------------------------------------------------------------------
# CRS validation
# ---------------------------------------------------------------------------

def validate_crs(crs_string: str) -> CRS:
    """
    Parse and validate a CRS authority string using pyproj.

    Parameters
    ----------
    crs_string:
        Any string accepted by pyproj, e.g. ``'EPSG:32644'``.

    Returns
    -------
    pyproj.CRS
        The validated CRS object.

    Raises
    ------
    InvalidCRSError
        If pyproj cannot parse the string.
    """
    try:
        crs = CRS.from_user_input(crs_string)
        logger.info("CRS validated: %s (%s)", crs_string, crs.name)
        return crs
    except CRSError as exc:
        raise InvalidCRSError(
            f"'{crs_string}' is not a valid CRS. "
            f"Use a recognised EPSG code such as 'EPSG:32644'. "
            f"pyproj reports: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

def _validate_latlon_range(lat: float, lon: float) -> None:
    """
    Raise InvalidCoordinateRangeError if converted values are out of bounds.

    Parameters
    ----------
    lat:
        Latitude in decimal degrees.
    lon:
        Longitude in decimal degrees.
    """
    if not (LATITUDE_MIN <= lat <= LATITUDE_MAX):
        raise InvalidCoordinateRangeError(
            f"Converted latitude {lat:.6f} is outside the valid range "
            f"[{LATITUDE_MIN}, {LATITUDE_MAX}]. "
            "Check that the correct source CRS was selected."
        )
    if not (LONGITUDE_MIN <= lon <= LONGITUDE_MAX):
        raise InvalidCoordinateRangeError(
            f"Converted longitude {lon:.6f} is outside the valid range "
            f"[{LONGITUDE_MIN}, {LONGITUDE_MAX}]. "
            "Check that the correct source CRS was selected."
        )


def convert_projected_to_latlon(
    easting: float,
    northing: float,
    source_crs: str,
) -> tuple[float, float]:
    """
    Transform a single (Easting, Northing) pair to (Latitude, Longitude).

    Parameters
    ----------
    easting:
        X-coordinate in the source projected CRS.
    northing:
        Y-coordinate in the source projected CRS.
    source_crs:
        Authority string for the source CRS, e.g. ``'EPSG:32644'``.

    Returns
    -------
    tuple[float, float]
        ``(latitude, longitude)`` in WGS84 decimal degrees.

    Raises
    ------
    InvalidCRSError
        If ``source_crs`` cannot be parsed.
    CoordinateConversionError
        If the pyproj transformation itself fails.
    InvalidCoordinateRangeError
        If the resulting lat/lon are outside valid bounds.
    """
    validate_crs(source_crs)  # raises InvalidCRSError if bad

    try:
        # always_xy=True → input order is (easting, northing),
        # output order is (longitude, latitude) regardless of CRS axis order.
        transformer = Transformer.from_crs(source_crs, TARGET_CRS, always_xy=True)
        lon, lat = transformer.transform(easting, northing)
    except Exception as exc:
        raise CoordinateConversionError(
            f"Failed to convert ({easting}, {northing}) from {source_crs}: {exc}"
        ) from exc

    _validate_latlon_range(lat, lon)
    logger.debug(
        "Converted (E=%.3f, N=%.3f) [%s] → lat=%.6f, lon=%.6f",
        easting, northing, source_crs, lat, lon,
    )
    return lat, lon


# ---------------------------------------------------------------------------
# Centroid helpers
# ---------------------------------------------------------------------------

def _compute_latlon_centroid(
    lats: list[float], lons: list[float]
) -> tuple[float, float]:
    """
    Compute the arithmetic mean centroid of a list of lat/lon pairs.

    For survey areas that span at most a few kilometres this is accurate
    enough; great-circle centroid algorithms are not necessary.

    Parameters
    ----------
    lats:
        List of latitude values in decimal degrees.
    lons:
        List of longitude values in decimal degrees.

    Returns
    -------
    tuple[float, float]
        ``(mean_latitude, mean_longitude)``
    """
    return sum(lats) / len(lats), sum(lons) / len(lons)


# ---------------------------------------------------------------------------
# Public API – high-level entry points
# ---------------------------------------------------------------------------

def extract_latlon_from_dataframe(df: pd.DataFrame) -> ConversionResult:
    """
    Extract geographic centroid coordinates from a DataFrame that already
    carries Latitude/Longitude columns.

    Parameters
    ----------
    df:
        Survey DataFrame containing ``Latitude`` and ``Longitude`` columns
        (or their aliases as defined in ``config.LATLON_ALIASES``).

    Returns
    -------
    ConversionResult
        Centroid computed from all valid rows.

    Raises
    ------
    CoordinateConversionError
        If no valid lat/lon pairs could be extracted.
    InvalidCoordinateRangeError
        If any value falls outside valid bounds.
    """
    # Resolve column names using aliases (case-insensitive)
    alias_lower: dict[str, str] = {k.lower(): v for k, v in LATLON_ALIASES.items()}
    col_map: dict[str, str] = {}
    for raw in df.columns:
        canonical = alias_lower.get(raw.strip().lower())
        if canonical in (COL_LATITUDE, COL_LONGITUDE):
            col_map[canonical] = raw  # canonical -> actual_col_in_df

    if COL_LATITUDE not in col_map or COL_LONGITUDE not in col_map:
        raise CoordinateConversionError(
            "DataFrame does not contain Latitude and Longitude columns."
        )

    lat_col = col_map[COL_LATITUDE]
    lon_col = col_map[COL_LONGITUDE]

    lats_raw = pd.to_numeric(df[lat_col], errors="coerce").dropna().tolist()
    lons_raw = pd.to_numeric(df[lon_col], errors="coerce").dropna().tolist()

    if not lats_raw or not lons_raw:
        raise CoordinateConversionError(
            "No valid numeric Latitude/Longitude values found in the file."
        )

    # Validate each pair
    for lat, lon in zip(lats_raw, lons_raw):
        _validate_latlon_range(lat, lon)

    centroid_lat, centroid_lon = _compute_latlon_centroid(lats_raw, lons_raw)

    logger.info(
        "Lat/lon extracted from file: %d points, centroid=(%.6f, %.6f).",
        len(lats_raw), centroid_lat, centroid_lon,
    )

    return ConversionResult(
        latitude=centroid_lat,
        longitude=centroid_lon,
        source_crs="EPSG:4326",
        point_count=len(lats_raw),
        was_converted=False,
    )


def convert_dataframe_to_latlon(
    df: pd.DataFrame,
    source_crs: str,
) -> ConversionResult:
    """
    Convert all (Easting, Northing) pairs in a DataFrame to geographic
    coordinates and return the centroid.

    Parameters
    ----------
    df:
        Survey DataFrame with ``Easting`` and ``Northing`` columns.
    source_crs:
        Authority string of the source projected CRS, e.g. ``'EPSG:32644'``.

    Returns
    -------
    ConversionResult
        Centroid in WGS84 lat/lon.

    Raises
    ------
    InvalidCRSError
        If ``source_crs`` is not valid.
    CoordinateConversionError
        If any individual conversion fails.
    InvalidCoordinateRangeError
        If converted values are out of bounds.
    """
    validate_crs(source_crs)  # fail fast before iterating all rows

    clean = df[[COL_EASTING, COL_NORTHING]].dropna()
    if clean.empty:
        raise CoordinateConversionError(
            "No valid Easting/Northing pairs found for conversion."
        )

    lats: list[float] = []
    lons: list[float] = []

    for _, row in clean.iterrows():
        lat, lon = convert_projected_to_latlon(
            float(row[COL_EASTING]),
            float(row[COL_NORTHING]),
            source_crs,
        )
        lats.append(lat)
        lons.append(lon)

    centroid_lat, centroid_lon = _compute_latlon_centroid(lats, lons)

    logger.info(
        "Projected→geographic conversion: %d points, CRS=%s, "
        "centroid=(%.6f, %.6f).",
        len(lats), source_crs, centroid_lat, centroid_lon,
    )

    return ConversionResult(
        latitude=centroid_lat,
        longitude=centroid_lon,
        source_crs=source_crs,
        point_count=len(lats),
        was_converted=True,
    )
