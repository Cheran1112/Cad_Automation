"""
solar_layout/layout_engine.py
------------------------------
High-level orchestrator for the Solar Layout Planning pipeline.

Single responsibility: coordinate every step from raw land boundary to a
complete, structured layout result.  Business logic lives in the specialist
modules; this file only wires them together.

Pipeline
--------
1.  Convert the existing project's Polyline / coordinate list to a Shapely
    Polygon (via geometry_utils).
2.  Apply engineering constraints (setback, corridor) to get the usable area.
3.  Run the panel placement optimiser.
4.  Compute capacity and layout efficiency metrics.
5.  Return a single :class:`SolarLayoutResult` object.

The engine never touches Streamlit, DXF, or any existing project module
other than reading ``geometry.polyline.Polyline`` and
``geometry.calculator.GeometryMetrics`` — both are already in session state
when this module is called.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from shapely.geometry import Polygon

from solar_layout.capacity_calculator import CapacityResult, compute_capacity
from solar_layout.config import (
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    SOLAR_MODULE_ENABLED,
)
from solar_layout.geometry_utils import coords_to_polygon, polygon_area_m2
from solar_layout.panel_optimizer import (
    PanelPlacementResult,
    optimise_orientation,
    place_panels,
)
from solar_layout.spacing_rules import SpacingRules, UsableAreaResult, compute_usable_area

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level result container
# ---------------------------------------------------------------------------

@dataclass
class SolarLayoutResult:
    """
    Complete output of the solar layout pipeline.

    Attributes
    ----------
    land_polygon:
        Shapely Polygon of the original land boundary.
    usable_area:
        Result of the usable-area computation (polygon + area breakdown).
    placement:
        Result of the panel placement optimiser.
    capacity:
        Computed electrical capacity and yield metrics.
    rules:
        The spacing rules used for this run.
    orientation_used:
        ``'portrait'``, ``'landscape'``, or ``'auto'`` (best of both).
    succeeded:
        True when at least one panel was placed.
    error:
        Human-readable error message when succeeded is False.
    warnings:
        Non-fatal advisory messages.
    """

    land_polygon: Polygon | None = None
    usable_area: UsableAreaResult | None = None
    placement: PanelPlacementResult | None = None
    capacity: CapacityResult | None = None
    rules: SpacingRules | None = None
    orientation_used: str = ""
    succeeded: bool = False
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience accessors (all guard against None)
    # ------------------------------------------------------------------

    @property
    def panel_count(self) -> int:
        return self.placement.panel_count if self.placement else 0

    @property
    def total_area_m2(self) -> float:
        return self.usable_area.total_area_m2 if self.usable_area else 0.0

    @property
    def usable_area_m2(self) -> float:
        return self.usable_area.usable_area_m2 if self.usable_area else 0.0

    @property
    def total_panel_area_m2(self) -> float:
        return self.placement.total_panel_area_m2 if self.placement else 0.0

    @property
    def remaining_area_m2(self) -> float:
        return self.usable_area_m2 - self.total_panel_area_m2

    @property
    def layout_efficiency_pct(self) -> float:
        """Panel area as a percentage of usable area."""
        if not self.usable_area or self.usable_area.usable_area_m2 <= 0:
            return 0.0
        return 100.0 * self.total_panel_area_m2 / self.usable_area.usable_area_m2

    @property
    def ground_coverage_ratio(self) -> float:
        """Panel area as a fraction of total land area (GCR)."""
        if not self.usable_area or self.usable_area.total_area_m2 <= 0:
            return 0.0
        return self.total_panel_area_m2 / self.usable_area.total_area_m2

    @property
    def installed_capacity_kwp(self) -> float:
        return self.capacity.installed_capacity_kwp if self.capacity else 0.0

    @property
    def installed_capacity_mwp(self) -> float:
        return self.capacity.installed_capacity_mwp if self.capacity else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_solar_layout(
    coords: Sequence[tuple[float, float]],
    rules: SpacingRules | None = None,
    orientation: str = "auto",
) -> SolarLayoutResult:
    """
    Execute the complete Solar Layout Planning pipeline.

    Parameters
    ----------
    coords:
        Ordered ``(easting, northing)`` tuples from the existing project's
        ``Polyline.coordinates``.  Must form a valid closed polygon.
    rules:
        Engineering constraints.  When ``None`` a default :class:`SpacingRules`
        instance is constructed from ``solar_layout.config`` values.
    orientation:
        ``'portrait'``, ``'landscape'``, or ``'auto'`` (try both, keep best).

    Returns
    -------
    SolarLayoutResult
        Always returned — never raises.  Inspect ``.succeeded`` and
        ``.error`` to determine whether the pipeline completed.
    """
    if not SOLAR_MODULE_ENABLED:
        result = SolarLayoutResult()
        result.error = "Solar Layout module is disabled (SOLAR_MODULE_ENABLED=False)."
        return result

    result = SolarLayoutResult()

    # ------------------------------------------------------------------
    # Step 1 – Build land polygon
    # ------------------------------------------------------------------
    try:
        land_polygon = coords_to_polygon(list(coords))
        result.land_polygon = land_polygon
        logger.info(
            "Land polygon built: %.4f m², %d vertices.",
            land_polygon.area,
            len(list(land_polygon.exterior.coords)) - 1,
        )
    except Exception as exc:
        result.error = f"Failed to build land polygon from coordinates: {exc}"
        logger.exception("Land polygon construction failed.")
        return result

    # ------------------------------------------------------------------
    # Step 2 – Resolve spacing rules
    # ------------------------------------------------------------------
    try:
        if rules is None:
            # Use orientation to build the default rules object
            orient = orientation if orientation in (
                ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE
            ) else ORIENTATION_PORTRAIT
            rules = SpacingRules(orientation=orient)
        result.rules = rules
        logger.info("Using spacing rules: %s", rules)
    except Exception as exc:
        result.error = f"Invalid spacing rules: {exc}"
        logger.exception("SpacingRules construction failed.")
        return result

    # ------------------------------------------------------------------
    # Step 3 – Compute usable area
    # ------------------------------------------------------------------
    try:
        usable = compute_usable_area(land_polygon, rules)
        result.usable_area = usable

        if not usable.is_viable:
            result.warnings.append(
                f"Usable area ({usable.usable_area_m2:.2f} m²) is very small. "
                "Layout may place no panels. Consider reducing the setback."
            )
    except ValueError as exc:
        result.error = str(exc)
        logger.warning("Usable area computation failed: %s", exc)
        return result
    except Exception as exc:
        result.error = f"Unexpected error computing usable area: {exc}"
        logger.exception("Usable area computation error.")
        return result

    # ------------------------------------------------------------------
    # Step 4 – Place panels
    # ------------------------------------------------------------------
    try:
        if orientation == "auto":
            portrait_rules = SpacingRules(
                boundary_setback_m=rules.boundary_setback_m,
                inter_panel_gap_m=rules.inter_panel_gap_m,
                inter_column_gap_m=rules.inter_column_gap_m,
                inter_row_spacing_m=rules.inter_row_spacing_m,
                utility_corridor_width_m=rules.utility_corridor_width_m,
                orientation=ORIENTATION_PORTRAIT,
                panels_per_string=rules.panels_per_string,
            )
            landscape_rules = SpacingRules(
                boundary_setback_m=rules.boundary_setback_m,
                inter_panel_gap_m=rules.inter_panel_gap_m,
                inter_column_gap_m=rules.inter_column_gap_m,
                inter_row_spacing_m=rules.inter_row_spacing_m,
                utility_corridor_width_m=rules.utility_corridor_width_m,
                orientation=ORIENTATION_LANDSCAPE,
                panels_per_string=rules.panels_per_string,
            )
            placement, best_orient = optimise_orientation(
                usable.usable_polygon, portrait_rules, landscape_rules
            )
            # Update result.rules to reflect the winning orientation
            result.rules = portrait_rules if best_orient == ORIENTATION_PORTRAIT else landscape_rules
            result.orientation_used = best_orient
            logger.info("Auto-orientation selected: %s.", best_orient)
        else:
            placement = place_panels(usable.usable_polygon, rules)
            result.orientation_used = rules.orientation

        result.placement = placement

        if placement.panel_count == 0:
            result.warnings.append(
                "No panels could be placed inside the usable area. "
                "The land parcel may be too small or the spacing constraints too strict."
            )
            result.succeeded = False
            # Still return a result — capacity will be zero
        else:
            result.succeeded = True

    except Exception as exc:
        result.error = f"Panel placement failed: {exc}"
        logger.exception("Panel placement error.")
        return result

    # ------------------------------------------------------------------
    # Step 5 – Compute capacity
    # ------------------------------------------------------------------
    try:
        capacity = compute_capacity(placement.panel_count)
        result.capacity = capacity
        logger.info(
            "Capacity: %.2f kWp (%.4f MWp), %d panels.",
            capacity.installed_capacity_kwp,
            capacity.installed_capacity_mwp,
            placement.panel_count,
        )
    except Exception as exc:
        result.warnings.append(f"Capacity calculation failed: {exc}")
        logger.warning("Capacity calculation error: %s", exc)

    logger.info(
        "Solar layout pipeline complete: succeeded=%s, panels=%d, "
        "capacity=%.2f kWp, efficiency=%.1f %%.",
        result.succeeded,
        result.panel_count,
        result.installed_capacity_kwp,
        result.layout_efficiency_pct,
    )

    return result
