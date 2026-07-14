"""
data/reader.py
--------------
Responsible for reading survey coordinate data from Excel (.xlsx) and CSV (.csv)
files into a normalised pandas DataFrame.

Single responsibility: file I/O and column normalisation only.
Validation lives in validation/validator.py.

Coordinate-format support
--------------------------
Format A – Easting/Northing (projected):
    Point_ID | Easting | Northing
    Passed through unchanged.  100 % backward-compatible.

Format B – Latitude/Longitude (geographic):
    Point_ID | Latitude | Longitude
    Automatically converted to UTM Easting/Northing using pyproj.
    The UTM zone is determined from the mean longitude so the caller
    never needs to specify a CRS.

In both cases the function returns the same DataFrame shape
(Point_ID / Easting / Northing) so every downstream module
(validation, geometry, DXF, preview) is completely unaffected.

The :class:`ReadResult` named-tuple carries optional metadata about the
detected format and CRS so the UI can show an informational banner.
"""

from __future__ import annotations

import io
import logging
import math
from pathlib import Path
from typing import NamedTuple, Union

import pandas as pd
from pyproj import Transformer

from config import (
    COL_EASTING,
    COL_LATITUDE,
    COL_LONGITUDE,
    COL_NORTHING,
    COL_POINT_ID,
    COLUMN_ALIASES,
    LATLON_ALIASES,
    REQUIRED_COLUMNS,
)

logger = logging.getLogger(__name__)

# Type alias accepted by every public function
FileSource = Union[str, Path, io.BytesIO]


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

class ReadResult(NamedTuple):
    """
    Return value of :func:`read_file`.

    Attributes
    ----------
    df:
        Normalised DataFrame with columns Point_ID / Easting / Northing.
    coord_format:
        ``'easting_northing'`` when the file used projected coordinates.
        ``'latitude_longitude'`` when Lat/Lon were detected and converted.
    source_crs:
        CRS of the original file data.
        ``'EPSG:4326'`` for lat/lon files, ``'native'`` for projected files.
    target_epsg:
        UTM EPSG code used for the conversion, e.g. ``'EPSG:32644'``.
        Empty string when no conversion was performed.
    """

    df: pd.DataFrame
    coord_format: str           # 'easting_northing' | 'latitude_longitude'
    source_crs: str             # 'native' | 'EPSG:4326'
    target_epsg: str            # '' | 'EPSG:32644' etc.


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file extension is not .xlsx or .csv."""


class FileReadError(Exception):
    """Raised when pandas fails to parse the file."""


# ---------------------------------------------------------------------------
# UTM zone helper
# ---------------------------------------------------------------------------

def _utm_epsg_from_longitude(mean_lon: float, mean_lat: float) -> str:
    """
    Derive the correct UTM EPSG code from mean longitude and latitude.

    Parameters
    ----------
    mean_lon:
        Mean longitude of all survey points (decimal degrees, WGS84).
    mean_lat:
        Mean latitude of all survey points (decimal degrees, WGS84).

    Returns
    -------
    str
        EPSG authority string, e.g. ``'EPSG:32644'``.
    """
    zone_number = int((mean_lon + 180) / 6) + 1
    # Northern hemisphere: 326xx  /  Southern hemisphere: 327xx
    base = 32600 if mean_lat >= 0 else 32700
    epsg = f"EPSG:{base + zone_number}"
    logger.info(
        "Auto-detected UTM zone %d%s → %s",
        zone_number,
        "N" if mean_lat >= 0 else "S",
        epsg,
    )
    return epsg


# ---------------------------------------------------------------------------
# Column detection helpers
# ---------------------------------------------------------------------------

def _detect_columns(raw_columns: list[str]) -> str:
    """
    Inspect the raw column list and decide which coordinate format is present.

    Parameters
    ----------
    raw_columns:
        Column names exactly as read from the file (before any normalisation).

    Returns
    -------
    str
        ``'easting_northing'`` – Easting and Northing columns detected.
        ``'latitude_longitude'`` – Latitude and Longitude columns detected.

    Raises
    ------
    KeyError
        When neither format can be identified.
    """
    # Build lower-case sets for both families
    en_lower  = {v.lower() for v in COLUMN_ALIASES.values()
                 if v in (COL_EASTING, COL_NORTHING)}
    ll_lower  = {k.lower() for k in LATLON_ALIASES}

    cols_lower = {str(c).strip().lower() for c in raw_columns}

    has_easting  = bool(cols_lower & {COL_EASTING.lower(),  "east",  "e",  "x"})
    has_northing = bool(cols_lower & {COL_NORTHING.lower(), "north", "n",  "y"})
    has_lat      = bool(cols_lower & {k.lower() for k, v in LATLON_ALIASES.items()
                                      if v == COL_LATITUDE})
    has_lon      = bool(cols_lower & {k.lower() for k, v in LATLON_ALIASES.items()
                                      if v == COL_LONGITUDE})

    if has_easting and has_northing:
        return "easting_northing"
    if has_lat and has_lon:
        return "latitude_longitude"

    # Neither format recognised – build a helpful error
    raise KeyError(
        "File does not contain a recognised coordinate format. "
        "Expected either:\n"
        "  • Easting + Northing  (projected)\n"
        "  • Latitude + Longitude  (geographic)\n"
        f"File contains columns: {list(raw_columns)}"
    )


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strip whitespace and resolve column names to their canonical form using
    COLUMN_ALIASES (Easting/Northing family) defined in config.py.

    Called only after :func:`_detect_columns` has confirmed the file uses
    the Easting/Northing format.

    Parameters
    ----------
    df:
        Raw DataFrame with projected coordinate columns.

    Returns
    -------
    pd.DataFrame
        Columns: Point_ID (str), Easting (float64), Northing (float64).

    Raises
    ------
    KeyError
        If a required column is still missing after alias resolution.
    """
    # Build lower-case alias map covering both REQUIRED_COLUMNS and COLUMN_ALIASES
    canonical_map: dict[str, str] = {}
    for col in REQUIRED_COLUMNS:
        canonical_map[col.lower()] = col
    for alias, canonical in COLUMN_ALIASES.items():
        canonical_map[alias.lower()] = canonical

    rename: dict[str, str] = {}
    found: set[str] = set()

    for raw_col in df.columns:
        stripped = str(raw_col).strip()
        lower = stripped.lower()
        if lower in canonical_map:
            canonical = canonical_map[lower]
            if canonical not in found:          # first match wins
                rename[raw_col] = canonical
                found.add(canonical)
                if stripped != canonical:
                    logger.info("Renamed column '%s' → '%s'", stripped, canonical)

    missing = [c for c in REQUIRED_COLUMNS if c not in found]
    if missing:
        raise KeyError(
            f"Required column(s) not found in file: {missing}. "
            f"File contains: {list(df.columns)}"
        )

    df = df.rename(columns=rename)
    df = df[[COL_POINT_ID, COL_EASTING, COL_NORTHING]].copy()
    df[COL_POINT_ID] = df[COL_POINT_ID].astype(str).str.strip()
    return df


def _normalise_latlon_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resolve column names for a Latitude/Longitude file.

    Uses LATLON_ALIASES from config.py plus the Point_ID family from
    COLUMN_ALIASES.  Returns a DataFrame with exactly three columns:
    Point_ID, Latitude, Longitude.

    Parameters
    ----------
    df:
        Raw DataFrame with geographic coordinate columns.

    Returns
    -------
    pd.DataFrame
        Columns: Point_ID (str), Latitude (float64), Longitude (float64).
    """
    # Combined lower-case map: point-id aliases + lat/lon aliases
    combined: dict[str, str] = {}
    for alias, canonical in COLUMN_ALIASES.items():
        if canonical == COL_POINT_ID:
            combined[alias.lower()] = COL_POINT_ID
    combined[COL_POINT_ID.lower()] = COL_POINT_ID

    for alias, canonical in LATLON_ALIASES.items():
        combined[alias.lower()] = canonical

    rename: dict[str, str] = {}
    found: set[str] = set()

    for raw_col in df.columns:
        stripped = str(raw_col).strip()
        lower = stripped.lower()
        canonical = combined.get(lower)
        if canonical and canonical not in found:
            rename[raw_col] = canonical
            found.add(canonical)
            if stripped != canonical:
                logger.info("Renamed column '%s' → '%s'", stripped, canonical)

    needed = {COL_POINT_ID, COL_LATITUDE, COL_LONGITUDE}
    missing = needed - found
    if missing:
        raise KeyError(
            f"Required column(s) not found: {sorted(missing)}. "
            f"File contains: {list(df.columns)}"
        )

    df = df.rename(columns=rename)
    df = df[[COL_POINT_ID, COL_LATITUDE, COL_LONGITUDE]].copy()
    df[COL_POINT_ID]  = df[COL_POINT_ID].astype(str).str.strip()
    df[COL_LATITUDE]  = pd.to_numeric(df[COL_LATITUDE],  errors="coerce")
    df[COL_LONGITUDE] = pd.to_numeric(df[COL_LONGITUDE], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Lat/Lon → UTM conversion
# ---------------------------------------------------------------------------

def _convert_latlon_to_utm(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """
    Convert a Latitude/Longitude DataFrame to UTM Easting/Northing in place.

    The target UTM zone is determined automatically from the mean longitude
    of all points, so no user input is required.

    Parameters
    ----------
    df:
        DataFrame with columns Point_ID, Latitude, Longitude
        (as returned by :func:`_normalise_latlon_columns`).

    Returns
    -------
    tuple[pd.DataFrame, str]
        * Converted DataFrame with columns Point_ID, Easting, Northing.
        * EPSG code of the target UTM CRS, e.g. ``'EPSG:32644'``.

    Raises
    ------
    FileReadError
        If the pyproj transformation fails for any reason.
    """
    # Drop rows with missing coordinates before conversion
    clean = df.dropna(subset=[COL_LATITUDE, COL_LONGITUDE])

    if clean.empty:
        raise FileReadError("No valid Latitude/Longitude values found for conversion.")

    mean_lat = float(clean[COL_LATITUDE].mean())
    mean_lon = float(clean[COL_LONGITUDE].mean())

    target_epsg = _utm_epsg_from_longitude(mean_lon, mean_lat)

    logger.info(
        "Converting %d point(s) from EPSG:4326 → %s",
        len(clean), target_epsg,
    )

    try:
        # always_xy=True: input (longitude, latitude), output (easting, northing)
        transformer = Transformer.from_crs("EPSG:4326", target_epsg, always_xy=True)
        eastings, northings = transformer.transform(
            clean[COL_LONGITUDE].tolist(),
            clean[COL_LATITUDE].tolist(),
        )
    except Exception as exc:
        raise FileReadError(
            f"Coordinate conversion from EPSG:4326 to {target_epsg} failed: {exc}"
        ) from exc

    result = clean[[COL_POINT_ID]].copy().reset_index(drop=True)
    result[COL_EASTING]  = list(eastings)
    result[COL_NORTHING] = list(northings)

    logger.info(
        "Conversion complete → %s: E[%.2f … %.2f], N[%.2f … %.2f]",
        target_epsg,
        result[COL_EASTING].min(),  result[COL_EASTING].max(),
        result[COL_NORTHING].min(), result[COL_NORTHING].max(),
    )

    return result, target_epsg


# ---------------------------------------------------------------------------
# Numeric coercion
# ---------------------------------------------------------------------------

def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce Easting and Northing columns to float64.

    Non-convertible cells become NaN so the validator can catch them with a
    meaningful message rather than a raw pandas exception.

    Parameters
    ----------
    df:
        DataFrame with normalised column names.

    Returns
    -------
    pd.DataFrame
        Same DataFrame with Easting/Northing as float64.
    """
    for col in (COL_EASTING, COL_NORTHING):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Raw file reading
# ---------------------------------------------------------------------------

def _read_raw(source: FileSource, ext: str) -> pd.DataFrame:
    """
    Read the raw bytes into a pandas DataFrame without any normalisation.

    Parameters
    ----------
    source:
        File path or binary stream.
    ext:
        Lowercase file extension: ``'.xlsx'`` or ``'.csv'``.

    Returns
    -------
    pd.DataFrame
        Raw DataFrame, all columns as str dtype.

    Raises
    ------
    FileReadError
        On any pandas parse failure.
    """
    try:
        if ext == ".xlsx":
            return pd.read_excel(source, engine="openpyxl", dtype=str)

        # CSV – try UTF-8 first then latin-1
        if isinstance(source, (str, Path)):
            try:
                return pd.read_csv(source, dtype=str, encoding="utf-8")
            except UnicodeDecodeError:
                return pd.read_csv(source, dtype=str, encoding="latin-1")
        else:
            raw_bytes = source.read()
            source.seek(0)
            for enc in ("utf-8", "latin-1"):
                try:
                    return pd.read_csv(io.BytesIO(raw_bytes), dtype=str, encoding=enc)
                except UnicodeDecodeError:
                    continue
            raise FileReadError(
                "Could not decode CSV file with UTF-8 or Latin-1 encoding."
            )
    except (FileReadError, UnsupportedFileTypeError):
        raise
    except Exception as exc:
        raise FileReadError(f"Failed to parse file: {exc}") from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_file(source: FileSource, filename: str = "") -> ReadResult:
    """
    Read an Excel or CSV file and return a normalised :class:`ReadResult`.

    Supports two coordinate formats automatically:

    **Format A – Easting/Northing (projected)**
        Columns Point_ID / Easting / Northing (or any alias).
        Passed through unchanged — 100 % backward-compatible.

    **Format B – Latitude/Longitude (geographic)**
        Columns Point_ID / Latitude / Longitude (or any alias).
        Converted to UTM Easting/Northing using pyproj.
        UTM zone is auto-detected from the mean longitude.

    In both cases the returned DataFrame has the same three-column shape
    (Point_ID / Easting / Northing) so every downstream module is
    completely unaffected.

    Parameters
    ----------
    source:
        A file path (str or Path) *or* a binary stream (e.g. from
        Streamlit's ``st.file_uploader``).
    filename:
        Original filename string.  Required when *source* is a BytesIO so
        the function can detect the extension.

    Returns
    -------
    ReadResult
        Named tuple: ``(df, coord_format, source_crs, target_epsg)``.

    Raises
    ------
    UnsupportedFileTypeError
        File extension is not .xlsx or .csv.
    FileReadError
        pandas cannot parse the file content.
    KeyError
        Neither a recognised Easting/Northing nor Latitude/Longitude column
        set is found in the file.
    """
    # ── Extension check ───────────────────────────────────────────────────
    if isinstance(source, (str, Path)):
        ext = Path(source).suffix.lower()
    else:
        ext = Path(filename).suffix.lower()

    if ext not in (".xlsx", ".csv"):
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext}'. Please upload a .xlsx or .csv file."
        )

    logger.info("Reading file: ext=%s, source_type=%s", ext, type(source).__name__)

    # ── Raw read ──────────────────────────────────────────────────────────
    df_raw = _read_raw(source, ext)
    df_raw = df_raw.dropna(how="all").reset_index(drop=True)

    # ── Format detection ──────────────────────────────────────────────────
    coord_format = _detect_columns(list(df_raw.columns))

    # ── Format A: Easting / Northing (existing path, completely unchanged) ─
    if coord_format == "easting_northing":
        df = _normalise_columns(df_raw)
        df = _coerce_numeric(df)
        df = df.reset_index(drop=True)

        logger.info(
            "File read successfully [%s]: %d rows.",
            coord_format, len(df),
        )
        return ReadResult(
            df=df,
            coord_format=coord_format,
            source_crs="native",
            target_epsg="",
        )

    # ── Format B: Latitude / Longitude (new path, converts to UTM) ────────
    df_ll = _normalise_latlon_columns(df_raw)
    df_utm, target_epsg = _convert_latlon_to_utm(df_ll)
    df_utm = df_utm.reset_index(drop=True)

    logger.info(
        "File read successfully [%s → %s]: %d rows.",
        coord_format, target_epsg, len(df_utm),
    )
    return ReadResult(
        df=df_utm,
        coord_format=coord_format,
        source_crs="EPSG:4326",
        target_epsg=target_epsg,
    )


def dataframe_summary(df: pd.DataFrame) -> dict[str, object]:
    """
    Return a lightweight summary dictionary for display in the UI.

    Parameters
    ----------
    df:
        Normalised DataFrame returned by :func:`read_file`.

    Returns
    -------
    dict
        Keys: ``row_count``, ``has_nulls``, ``easting_range``,
        ``northing_range``, ``point_ids``.
    """
    return {
        "row_count": len(df),
        "has_nulls": bool(df.isnull().any().any()),
        "easting_range": (
            float(df[COL_EASTING].min()),
            float(df[COL_EASTING].max()),
        ),
        "northing_range": (
            float(df[COL_NORTHING].min()),
            float(df[COL_NORTHING].max()),
        ),
        "point_ids": df[COL_POINT_ID].tolist(),
    }
