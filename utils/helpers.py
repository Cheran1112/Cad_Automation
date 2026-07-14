"""
utils/helpers.py
----------------
Shared, stateless helper functions used across the platform.

Single responsibility: lightweight formatting, unit conversion, and
file-path utilities that do not belong to any specific domain module.
No UI code, no geometry logic, no pandas operations.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Numeric formatting
# ---------------------------------------------------------------------------

def format_area(area_sq_m: float, *, decimals: int = 4) -> str:
    """
    Format a square-metre area value for human-readable display.

    Automatically selects the most appropriate unit:
    * < 10 000 m²  → display in m²
    * >= 10 000 m² → display in hectares (ha)

    Parameters
    ----------
    area_sq_m:
        Unsigned area in square metres.
    decimals:
        Number of decimal places.

    Returns
    -------
    str
        Formatted string including the unit label.

    Examples
    --------
    >>> format_area(4500.0)
    '4,500.0000 m²'
    >>> format_area(25000.0)
    '2.5000 ha'
    """
    if area_sq_m >= 10_000.0:
        return f"{area_sq_m / 10_000.0:,.{decimals}f} ha"
    return f"{area_sq_m:,.{decimals}f} m\u00b2"


def format_distance(metres: float, *, decimals: int = 3) -> str:
    """
    Format a distance value in metres.

    Parameters
    ----------
    metres:
        Distance in metres.
    decimals:
        Number of decimal places.

    Returns
    -------
    str
        Formatted string, e.g. ``'1,234.567 m'``.
    """
    return f"{metres:,.{decimals}f} m"


def format_coordinate(value: float, *, decimals: int = 3) -> str:
    """
    Format a single coordinate value (easting or northing).

    Parameters
    ----------
    value:
        Coordinate in metres.
    decimals:
        Number of decimal places.

    Returns
    -------
    str
        Formatted string, e.g. ``'518,980.691'``.
    """
    return f"{value:,.{decimals}f}"


def format_bearing(degrees: float) -> str:
    """
    Format a whole-circle bearing as ``DDD°MM'SS.ss"``.

    Parameters
    ----------
    degrees:
        Bearing in decimal degrees [0, 360).

    Returns
    -------
    str
        Formatted bearing string.

    Examples
    --------
    >>> format_bearing(45.5)
    "045°30'00.00\""
    """
    degrees = degrees % 360.0
    d = int(degrees)
    remainder = (degrees - d) * 60.0
    m = int(remainder)
    s = (remainder - m) * 60.0
    return f"{d:03d}\u00b0{m:02d}'{s:05.2f}\""


# ---------------------------------------------------------------------------
# File-path utilities
# ---------------------------------------------------------------------------

def timestamped_filename(base: str, extension: str) -> str:
    """
    Generate a filename with an ISO-8601-style timestamp suffix.

    Parameters
    ----------
    base:
        Base name without extension, e.g. ``'survey_boundary'``.
    extension:
        File extension without leading dot, e.g. ``'dxf'``.

    Returns
    -------
    str
        Filename string, e.g. ``'survey_boundary_20260713_143022.dxf'``.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{ts}.{extension}"


def ensure_output_dir(path: str | Path) -> Path:
    """
    Create the output directory (and any parents) if it does not exist.

    Parameters
    ----------
    path:
        Directory path to create.

    Returns
    -------
    pathlib.Path
        Resolved absolute path of the directory.
    """
    out = Path(path).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def safe_stem(filename: str) -> str:
    """
    Return the file stem (name without extension) stripped of whitespace
    and with spaces replaced by underscores — safe for use as a DXF layer
    name or output filename component.

    Parameters
    ----------
    filename:
        Original filename string (may include a path or extension).

    Returns
    -------
    str
        Sanitised stem string.

    Examples
    --------
    >>> safe_stem("My Survey File.xlsx")
    'My_Survey_File'
    """
    stem = Path(filename).stem.strip()
    return stem.replace(" ", "_")


# ---------------------------------------------------------------------------
# DataFrame display helpers
# ---------------------------------------------------------------------------

def build_metrics_table(metrics_dict: dict[str, object]) -> list[dict[str, str]]:
    """
    Convert a flat metrics dictionary into a list of ``{Metric, Value}``
    rows suitable for ``st.table()`` or ``st.dataframe()``.

    Parameters
    ----------
    metrics_dict:
        Mapping of label → value, e.g.
        ``{'Area': '4500.00 m²', 'Perimeter': '320.00 m'}``.

    Returns
    -------
    list[dict[str, str]]
        Each entry has keys ``'Metric'`` and ``'Value'``.
    """
    return [{"Metric": str(k), "Value": str(v)} for k, v in metrics_dict.items()]
