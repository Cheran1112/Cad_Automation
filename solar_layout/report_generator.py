"""
solar_layout/report_generator.py
----------------------------------
Converts a :class:`~solar_layout.layout_engine.SolarLayoutResult` into
display-ready data structures consumed by the Streamlit UI.

Single responsibility: data formatting for presentation only.
No geometry, no DXF, no Streamlit imports.

Produces:
- :class:`SolarReportSection` — a labelled group of metric rows.
- :class:`SolarReport`        — the complete structured report.
- JSON-serialisable dict for future PDF/Excel export.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from solar_layout.capacity_calculator import format_capacity, format_energy
from solar_layout.layout_engine import SolarLayoutResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ReportRow:
    """A single labelled metric row."""

    label: str
    value: str
    unit: str = ""
    icon: str = ""

    def display_value(self) -> str:
        """Return value + unit as a single string."""
        return f"{self.value} {self.unit}".strip()


@dataclass
class SolarReportSection:
    """A labelled group of :class:`ReportRow` entries."""

    title: str
    rows: list[ReportRow] = field(default_factory=list)
    icon: str = ""


@dataclass
class SolarReport:
    """
    Complete display-ready solar layout report.

    Attributes
    ----------
    sections:
        Ordered list of :class:`SolarReportSection` objects.
    succeeded:
        True when at least one panel was placed.
    panel_count:
        Total panels placed (convenience duplicate).
    capacity_label:
        Human-friendly capacity string (e.g. ``'142.35 kWp'``).
    orientation_used:
        ``'Portrait'`` or ``'Landscape'``.
    warnings:
        Non-fatal advisory messages from the pipeline.
    """

    sections: list[SolarReportSection] = field(default_factory=list)
    succeeded: bool = False
    panel_count: int = 0
    capacity_label: str = ""
    orientation_used: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal formatters
# ---------------------------------------------------------------------------

def _fmt_area(m2: float) -> str:
    """Format an area value, auto-switching to hectares above 10 000 m²."""
    if m2 >= 10_000:
        return f"{m2 / 10_000:.4f} ha  ({m2:,.1f} m²)"
    return f"{m2:,.2f} m²"


def _fmt_float(value: float, decimals: int = 3) -> str:
    return f"{value:.{decimals}f}"


def _fmt_pct(value: float) -> str:
    return f"{value:.2f} %"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _land_area_section(result: SolarLayoutResult) -> SolarReportSection:
    sec = SolarReportSection(title="Land Area Breakdown", icon="🗺")

    if result.usable_area is None:
        sec.rows.append(ReportRow(label="Status", value="No data"))
        return sec

    ua = result.usable_area
    sec.rows = [
        ReportRow(label="Total Land Area",       value=_fmt_area(ua.total_area_m2),           icon="📐"),
        ReportRow(label="Boundary Setback Loss", value=_fmt_area(ua.setback_loss_m2),          icon="↩"),
        ReportRow(label="Corridor Loss",         value=_fmt_area(ua.corridor_loss_m2),         icon="🛣"),
        ReportRow(label="Usable Area",           value=_fmt_area(ua.usable_area_m2),           icon="✅"),
        ReportRow(label="Usable Fraction",       value=_fmt_pct(ua.usable_fraction * 100.0),   icon="📊"),
    ]
    return sec


def _panel_layout_section(result: SolarLayoutResult) -> SolarReportSection:
    sec = SolarReportSection(title="Panel Layout", icon="☀")

    if result.placement is None:
        sec.rows.append(ReportRow(label="Status", value="No placement data"))
        return sec

    pl = result.placement
    rules = result.rules

    rows: list[ReportRow] = [
        ReportRow(label="Orientation",          value=result.orientation_used.capitalize(), icon="🔄"),
        ReportRow(label="Total Panels",         value=f"{pl.panel_count:,}",               icon="🔢"),
        ReportRow(label="Rows Placed",          value=f"{pl.rows_placed:,}",               icon="↔"),
        ReportRow(label="Total Panel Area",     value=_fmt_area(pl.total_panel_area_m2),   icon="📦"),
        ReportRow(label="Remaining Area",       value=_fmt_area(result.remaining_area_m2), icon="⬜"),
        ReportRow(label="Layout Efficiency",    value=_fmt_pct(result.layout_efficiency_pct), icon="📈"),
        ReportRow(label="Ground Coverage Ratio",value=_fmt_float(result.ground_coverage_ratio, 4), icon="📉"),
    ]

    if rules is not None:
        rows += [
            ReportRow(label="Panel Size (W × H)",
                      value=f"{rules.panel_w:.3f} × {rules.panel_h:.3f} m", icon="📏"),
            ReportRow(label="Row Pitch",
                      value=f"{rules.row_pitch_m:.2f} m",  icon="↕"),
            ReportRow(label="Column Pitch",
                      value=f"{rules.column_pitch_m:.3f} m", icon="↔"),
            ReportRow(label="Boundary Setback",
                      value=f"{rules.boundary_setback_m:.1f} m", icon="↩"),
        ]

    sec.rows = rows
    return sec


def _capacity_section(result: SolarLayoutResult) -> SolarReportSection:
    sec = SolarReportSection(title="Electrical Capacity & Yield", icon="⚡")

    if result.capacity is None:
        sec.rows.append(ReportRow(label="Status", value="No capacity data"))
        return sec

    cap = result.capacity

    sec.rows = [
        ReportRow(label="DC Nameplate Capacity",
                  value=format_capacity(cap.installed_capacity_kwp), icon="🔋"),
        ReportRow(label="AC Output Capacity",
                  value=f"{cap.ac_capacity_kwac:,.2f} kW AC",        icon="🔌"),
        ReportRow(label="Panel Nameplate Power",
                  value=f"{cap.panel_power_wp:.0f} Wp/panel",         icon="☀"),
        ReportRow(label="Estimated Daily Yield",
                  value=format_energy(cap.estimated_daily_yield_kwh) + "/day", icon="📅"),
        ReportRow(label="Estimated Annual Yield",
                  value=format_energy(cap.estimated_annual_yield_kwh) + "/yr", icon="📆"),
        ReportRow(label="Performance Ratio",
                  value=_fmt_pct(cap.performance_ratio * 100.0), icon="🎯"),
        ReportRow(label="Peak Sun Hours",
                  value=f"{cap.peak_sun_hours:.1f} h/day",       icon="🌤"),
    ]
    return sec


def _engineering_notes_section(result: SolarLayoutResult) -> SolarReportSection:
    sec = SolarReportSection(title="Engineering Notes & Assumptions", icon="📝")
    rules = result.rules

    notes: list[str] = [
        "Layout uses a south-to-north, west-to-east raster scan.",
        "All panels are placed fully inside the usable boundary.",
        "Shadow analysis not included — row spacing is a fixed engineering estimate.",
        "Capacity figures are DC nameplate (STC conditions).",
        "Annual yield estimate uses a fixed performance ratio and peak sun hours.",
        "Terrain, shading, and soiling losses are not modelled.",
    ]

    if rules and result.capacity:
        notes.append(
            f"Panel type: monocrystalline bifacial "
            f"{rules.panel_w:.3f} m × {rules.panel_h:.3f} m, "
            f"{result.capacity.panel_power_wp:.0f} Wp (STC)."
        )
    elif rules:
        notes.append(f"Panel size: {rules.panel_w:.3f} m × {rules.panel_h:.3f} m.")

    for note in notes:
        sec.rows.append(ReportRow(label="•", value=note))

    return sec


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_solar_report(result: SolarLayoutResult) -> SolarReport:
    """
    Convert a :class:`~solar_layout.layout_engine.SolarLayoutResult` into a
    :class:`SolarReport` ready for rendering in the Streamlit UI.

    Parameters
    ----------
    result:
        The completed layout pipeline result.

    Returns
    -------
    SolarReport
        Always returns a populated object.  Fields are ``'N/A'`` or empty
        when data is absent so the UI renders gracefully.
    """
    report = SolarReport()
    report.succeeded = result.succeeded
    report.panel_count = result.panel_count
    report.capacity_label = (
        format_capacity(result.installed_capacity_kwp)
        if result.capacity else "N/A"
    )
    report.orientation_used = result.orientation_used.capitalize()
    report.warnings = list(result.warnings)

    report.sections = [
        _land_area_section(result),
        _panel_layout_section(result),
        _capacity_section(result),
        _engineering_notes_section(result),
    ]

    logger.info(
        "Solar report built: panels=%d, capacity=%s, sections=%d.",
        report.panel_count,
        report.capacity_label,
        len(report.sections),
    )
    return report


def solar_report_to_dict(result: SolarLayoutResult) -> dict[str, Any]:
    """
    Produce a JSON-serialisable dictionary of the complete layout result.

    Suitable for writing to a ``.json`` sidecar file or feeding a future
    PDF/Excel report generator.

    Parameters
    ----------
    result:
        The completed layout pipeline result.

    Returns
    -------
    dict
        Flat and nested key-value structure covering all metrics.
    """
    cap = result.capacity
    ua = result.usable_area
    pl = result.placement
    rules = result.rules

    data: dict[str, Any] = {
        "succeeded": result.succeeded,
        "orientation_used": result.orientation_used,
        "warnings": result.warnings,
        "land_area": {
            "total_m2":         round(ua.total_area_m2, 4)    if ua else None,
            "setback_loss_m2":  round(ua.setback_loss_m2, 4)  if ua else None,
            "corridor_loss_m2": round(ua.corridor_loss_m2, 4) if ua else None,
            "usable_m2":        round(ua.usable_area_m2, 4)   if ua else None,
            "usable_fraction":  round(ua.usable_fraction, 6)  if ua else None,
        },
        "panel_layout": {
            "panel_count":           result.panel_count,
            "rows_placed":           pl.rows_placed if pl else 0,
            "total_panel_area_m2":   round(result.total_panel_area_m2, 4),
            "remaining_area_m2":     round(result.remaining_area_m2, 4),
            "layout_efficiency_pct": round(result.layout_efficiency_pct, 4),
            "ground_coverage_ratio": round(result.ground_coverage_ratio, 6),
        },
        "spacing_rules": {
            "boundary_setback_m":       rules.boundary_setback_m       if rules else None,
            "inter_row_spacing_m":      rules.inter_row_spacing_m      if rules else None,
            "inter_panel_gap_m":        rules.inter_panel_gap_m        if rules else None,
            "inter_column_gap_m":       rules.inter_column_gap_m       if rules else None,
            "utility_corridor_width_m": rules.utility_corridor_width_m if rules else None,
            "panel_w_m":                rules.panel_w                  if rules else None,
            "panel_h_m":                rules.panel_h                  if rules else None,
        },
        "capacity": {
            "panel_power_wp":      cap.panel_power_wp                          if cap else None,
            "installed_kwp":       round(cap.installed_capacity_kwp, 4)        if cap else None,
            "installed_mwp":       round(cap.installed_capacity_mwp, 6)        if cap else None,
            "ac_kw":               round(cap.ac_capacity_kwac, 4)              if cap else None,
            "daily_yield_kwh":     round(cap.estimated_daily_yield_kwh, 2)     if cap else None,
            "annual_yield_kwh":    round(cap.estimated_annual_yield_kwh, 2)    if cap else None,
            "annual_yield_mwh":    round(cap.estimated_annual_yield_mwh, 4)    if cap else None,
            "performance_ratio":   cap.performance_ratio                       if cap else None,
            "peak_sun_hours":      cap.peak_sun_hours                          if cap else None,
        },
    }
    return data


def solar_report_to_json(result: SolarLayoutResult, indent: int = 2) -> str:
    """
    Serialise the layout result to a formatted JSON string.

    Parameters
    ----------
    result:
        The completed layout pipeline result.
    indent:
        JSON indentation level.

    Returns
    -------
    str
        Pretty-printed JSON.
    """
    return json.dumps(solar_report_to_dict(result), indent=indent)
