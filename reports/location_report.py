"""
reports/location_report.py
---------------------------
Responsible for converting a :class:`~location.location_service.LocationResult`
into display-ready data structures consumed by the Streamlit UI.

Single responsibility: data formatting for presentation only.
No geocoding, no coordinate conversion, no Streamlit imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from location.location_service import LocationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LocationReportRow:
    """A single labelled field for tabular display."""
    label: str
    value: str
    icon: str = ""


@dataclass
class LocationReport:
    """
    Display-ready representation of a :class:`LocationResult`.

    Attributes
    ----------
    rows:
        Ordered list of :class:`LocationReportRow` entries for the UI table.
    google_maps_url:
        Direct Google Maps link (empty string if unavailable).
    latitude:
        Centroid latitude as a formatted string.
    longitude:
        Centroid longitude as a formatted string.
    coordinate_source:
        Human-readable description of where the coordinates came from.
    has_geocoding:
        True when place names are available.
    """

    rows: list[LocationReportRow] = field(default_factory=list)
    google_maps_url: str = ""
    latitude: str = ""
    longitude: str = ""
    coordinate_source: str = ""
    has_geocoding: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt_coord(value: float, decimals: int = 6) -> str:
    """Format a coordinate to the requested number of decimal places."""
    return f"{value:.{decimals}f}"


def _or_unknown(value: str) -> str:
    """Return the value if non-empty, else a readable placeholder."""
    return value.strip() if value and value.strip() else "—"


def _coordinate_source_label(result: LocationResult) -> str:
    """Build a one-line description of how coordinates were obtained."""
    if result.conversion is None:
        return "Coordinates unavailable"
    c = result.conversion
    if not c.was_converted:
        return (
            f"Read directly from file as Latitude/Longitude "
            f"({c.point_count} points)"
        )
    return (
        f"Converted from {c.source_crs} → WGS84 "
        f"({c.point_count} points, centroid)"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_location_report(result: LocationResult) -> LocationReport:
    """
    Convert a :class:`~location.location_service.LocationResult` into a
    :class:`LocationReport` ready for rendering in the Streamlit UI.

    Parameters
    ----------
    result:
        The outcome of ``location_service.detect_location()``.

    Returns
    -------
    LocationReport
        Always returns a populated object. When data is missing, fields
        contain ``'—'`` placeholders so the UI renders gracefully.
    """
    report = LocationReport()
    report.coordinate_source = _coordinate_source_label(result)
    report.google_maps_url = result.google_maps_url
    report.has_geocoding = result.has_geocoding

    if result.conversion:
        report.latitude = _fmt_coord(result.conversion.latitude)
        report.longitude = _fmt_coord(result.conversion.longitude)
    else:
        report.latitude = "—"
        report.longitude = "—"

    rows: list[LocationReportRow] = []
    rows.append(LocationReportRow(label="Latitude",  value=report.latitude,  icon="🌐"))
    rows.append(LocationReportRow(label="Longitude", value=report.longitude, icon="🌐"))

    if result.geocoding:
        g = result.geocoding
        rows.append(LocationReportRow(label="Country",          value=_or_unknown(g.country),         icon="🏳"))
        rows.append(LocationReportRow(label="State",            value=_or_unknown(g.state),            icon="📍"))
        rows.append(LocationReportRow(label="District",         value=_or_unknown(g.state_district),   icon="📍"))
        rows.append(LocationReportRow(label="City / Town",      value=_or_unknown(g.city),             icon="🏙"))
        rows.append(LocationReportRow(label="Area / Suburb",    value=_or_unknown(g.suburb),           icon="🏘"))
        rows.append(LocationReportRow(label="Postal Code",      value=_or_unknown(g.postcode),         icon="📮"))
        rows.append(LocationReportRow(label="Nearest Landmark", value=_or_unknown(g.nearest_landmark), icon="📌"))
    else:
        for lbl in ("Country", "State", "District", "City / Town",
                    "Area / Suburb", "Postal Code", "Nearest Landmark"):
            rows.append(LocationReportRow(label=lbl, value="—"))

    report.rows = rows

    logger.info(
        "Location report built: lat=%s, lon=%s, geocoding=%s.",
        report.latitude, report.longitude, report.has_geocoding,
    )
    return report
