"""
solar_layout/capacity_calculator.py
-------------------------------------
Electrical capacity and energy yield calculations for the solar layout.

Single responsibility: convert a panel count into engineering capacity
figures.  No geometry, no DXF, no UI.

All constants (panel power, losses, performance ratio) are imported from
``solar_layout.config`` so they can be tuned centrally without touching
this file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from solar_layout.config import (
    DC_LOSSES,
    INVERTER_EFFICIENCY,
    PANEL_HEIGHT_M,
    PANEL_POWER_WP,
    PANEL_WIDTH_M,
    PEAK_SUN_HOURS,
    PERFORMANCE_RATIO,
)

logger = logging.getLogger(__name__)

# Conversion constant
_W_PER_KW: float = 1_000.0
_W_PER_MW: float = 1_000_000.0
_DAYS_PER_YEAR: float = 365.0


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapacityResult:
    """
    Electrical sizing and estimated yield for a solar panel array.

    Attributes
    ----------
    panel_count:
        Number of panels placed.
    panel_power_wp:
        Nameplate power per panel (Watts-peak).
    installed_capacity_wp:
        Total DC nameplate capacity (Watts-peak).
    installed_capacity_kwp:
        Total DC nameplate capacity (kilo-Watts-peak).
    installed_capacity_mwp:
        Total DC nameplate capacity (Mega-Watts-peak).
    ac_capacity_kwac:
        AC output capacity after inverter efficiency (kW AC).
    estimated_daily_yield_kwh:
        Rough daily energy yield estimate (kWh/day).
        Based on: AC capacity × peak sun hours × performance ratio.
    estimated_annual_yield_kwh:
        Rough annual energy yield estimate (kWh/year).
    estimated_annual_yield_mwh:
        Same value expressed in MWh/year.
    panel_area_m2:
        Footprint area of a single panel (m²).
    total_panel_area_m2:
        Combined footprint area of all panels (m²).
    performance_ratio:
        The performance ratio used in yield estimates.
    peak_sun_hours:
        Peak sun hours/day used in yield estimates.
    """

    panel_count: int
    panel_power_wp: float
    installed_capacity_wp: float
    installed_capacity_kwp: float
    installed_capacity_mwp: float
    ac_capacity_kwac: float
    estimated_daily_yield_kwh: float
    estimated_annual_yield_kwh: float
    estimated_annual_yield_mwh: float
    panel_area_m2: float
    total_panel_area_m2: float
    performance_ratio: float
    peak_sun_hours: float

    def __str__(self) -> str:
        if self.installed_capacity_mwp >= 1.0:
            cap_str = f"{self.installed_capacity_mwp:.3f} MWp"
        else:
            cap_str = f"{self.installed_capacity_kwp:.2f} kWp"
        return (
            f"CapacityResult("
            f"panels={self.panel_count}, "
            f"capacity={cap_str}, "
            f"annual_yield={self.estimated_annual_yield_mwh:.2f} MWh/yr"
            f")"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_capacity(
    panel_count: int,
    panel_power_wp: float = PANEL_POWER_WP,
    inverter_efficiency: float = INVERTER_EFFICIENCY,
    dc_losses: float = DC_LOSSES,
    performance_ratio: float = PERFORMANCE_RATIO,
    peak_sun_hours: float = PEAK_SUN_HOURS,
) -> CapacityResult:
    """
    Compute installed capacity and estimated energy yield from panel count.

    Parameters
    ----------
    panel_count:
        Number of solar panels placed.
    panel_power_wp:
        Nameplate peak power per panel (Watts-peak).  Defaults to config value.
    inverter_efficiency:
        DC-to-AC conversion efficiency (0–1).  Defaults to config value.
    dc_losses:
        Fraction of DC power lost to cabling/mismatch (0–1).
    performance_ratio:
        Overall system performance ratio for energy yield (0–1).
    peak_sun_hours:
        Average peak sun hours per day for the site.

    Returns
    -------
    CapacityResult
        All capacity and yield figures.

    Raises
    ------
    ValueError
        When panel_count is negative or any efficiency is outside (0, 1].
    """
    if panel_count < 0:
        raise ValueError(f"panel_count must be ≥ 0; got {panel_count}.")
    if not 0 < inverter_efficiency <= 1.0:
        raise ValueError(f"inverter_efficiency must be in (0, 1]; got {inverter_efficiency}.")
    if not 0 <= dc_losses < 1.0:
        raise ValueError(f"dc_losses must be in [0, 1); got {dc_losses}.")
    if not 0 < performance_ratio <= 1.0:
        raise ValueError(f"performance_ratio must be in (0, 1]; got {performance_ratio}.")
    if peak_sun_hours <= 0:
        raise ValueError(f"peak_sun_hours must be > 0; got {peak_sun_hours}.")

    # DC nameplate
    installed_wp = panel_count * panel_power_wp
    installed_kwp = installed_wp / _W_PER_KW
    installed_mwp = installed_wp / _W_PER_MW

    # AC capacity (after DC losses and inverter)
    ac_kw = installed_kwp * (1.0 - dc_losses) * inverter_efficiency

    # Energy yield estimates
    # Daily: AC_kW × PSH × PR
    daily_kwh = ac_kw * peak_sun_hours * performance_ratio
    annual_kwh = daily_kwh * _DAYS_PER_YEAR
    annual_mwh = annual_kwh / _W_PER_KW  # kWh → MWh

    # Panel footprint
    single_panel_area = PANEL_WIDTH_M * PANEL_HEIGHT_M
    total_panel_area = panel_count * single_panel_area

    result = CapacityResult(
        panel_count=panel_count,
        panel_power_wp=panel_power_wp,
        installed_capacity_wp=installed_wp,
        installed_capacity_kwp=installed_kwp,
        installed_capacity_mwp=installed_mwp,
        ac_capacity_kwac=ac_kw,
        estimated_daily_yield_kwh=daily_kwh,
        estimated_annual_yield_kwh=annual_kwh,
        estimated_annual_yield_mwh=annual_mwh,
        panel_area_m2=single_panel_area,
        total_panel_area_m2=total_panel_area,
        performance_ratio=performance_ratio,
        peak_sun_hours=peak_sun_hours,
    )

    logger.info(
        "Capacity: %d panels × %.0f Wp = %.3f kWp DC / %.3f kW AC, "
        "~%.1f MWh/yr.",
        panel_count, panel_power_wp,
        installed_kwp, ac_kw,
        annual_mwh,
    )

    return result


def format_capacity(kwp: float) -> str:
    """
    Return a human-friendly capacity string, auto-selecting kWp or MWp.

    Parameters
    ----------
    kwp:
        Capacity in kilo-Watts-peak.

    Returns
    -------
    str
        e.g. ``'142.35 kWp'`` or ``'1.42 MWp'``.
    """
    if kwp >= 1_000.0:
        return f"{kwp / 1_000.0:.3f} MWp"
    return f"{kwp:.2f} kWp"


def format_energy(kwh: float) -> str:
    """
    Return a human-friendly energy string, auto-selecting kWh or MWh.

    Parameters
    ----------
    kwh:
        Energy in kilo-Watt-hours.
    """
    if kwh >= 1_000.0:
        return f"{kwh / 1_000.0:.2f} MWh"
    return f"{kwh:.1f} kWh"
