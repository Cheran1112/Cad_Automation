"""
solar_layout/spacing_rules.py
------------------------------
Engineering constraints dataclass and usable-area calculator.

Single responsibility: represent and apply all spacing/setback rules.
No panel placement logic, no DXF, no UI.

The :class:`SpacingRules` dataclass is the single object passed through the
pipeline so that every downstream component sees the same constraint set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shapely.geometry import Polygon

from solar_layout.config import (
    BOUNDARY_SETBACK_M,
    DEFAULT_ORIENTATION,
    INTER_COLUMN_GAP_M,
    INTER_PANEL_GAP_M,
    INTER_ROW_SPACING_M,
    MIN_USABLE_AREA_M2,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    PANEL_HEIGHT_M,
    PANEL_WIDTH_M,
    PANELS_PER_STRING,
    UTILITY_CORRIDOR_WIDTH_M,
)
from solar_layout.geometry_utils import (
    apply_setback,
    apply_utility_corridor,
    polygon_area_m2,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constraints dataclass
# ---------------------------------------------------------------------------

@dataclass
class SpacingRules:
    """
    All configurable engineering constraints for a solar panel layout.

    Attributes
    ----------
    boundary_setback_m:
        Inward setback from the land boundary (metres).
    inter_panel_gap_m:
        Structural tolerance gap between two panels in the same row (metres).
    inter_column_gap_m:
        Maintenance/cable-route gap between adjacent column groups (metres).
    inter_row_spacing_m:
        North-south distance between consecutive row bottom-edges (metres).
        This includes panel height plus the shadow-free access aisle.
    utility_corridor_width_m:
        Width of the reserved utility/road strip on the south edge (metres).
        Set to 0 to disable.
    orientation:
        ``'portrait'`` or ``'landscape'``.
    panels_per_string:
        Number of panels in one string (east-west).  0 = unrestricted.
    panel_w:
        Effective panel dimension in the east-west (X) direction (metres).
    panel_h:
        Effective panel dimension in the north-south (Y) direction (metres).
    """

    boundary_setback_m: float = BOUNDARY_SETBACK_M
    inter_panel_gap_m: float = INTER_PANEL_GAP_M
    inter_column_gap_m: float = INTER_COLUMN_GAP_M
    inter_row_spacing_m: float = INTER_ROW_SPACING_M
    utility_corridor_width_m: float = UTILITY_CORRIDOR_WIDTH_M
    orientation: str = DEFAULT_ORIENTATION
    panels_per_string: int = PANELS_PER_STRING

    # Derived panel dimensions (set in __post_init__)
    panel_w: float = field(init=False)
    panel_h: float = field(init=False)

    def __post_init__(self) -> None:
        self._resolve_panel_dims()
        self._validate()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_panel_dims(self) -> None:
        """
        Assign panel_w / panel_h based on the chosen orientation.

        Portrait  → width (shorter) on X, height (longer) on Y.
        Landscape → height (longer) on X, width (shorter) on Y.
        """
        if self.orientation == ORIENTATION_PORTRAIT:
            self.panel_w = PANEL_WIDTH_M
            self.panel_h = PANEL_HEIGHT_M
        elif self.orientation == ORIENTATION_LANDSCAPE:
            self.panel_w = PANEL_HEIGHT_M
            self.panel_h = PANEL_WIDTH_M
        else:
            logger.warning(
                "Unknown orientation '%s'; defaulting to portrait.", self.orientation
            )
            self.orientation = ORIENTATION_PORTRAIT
            self.panel_w = PANEL_WIDTH_M
            self.panel_h = PANEL_HEIGHT_M

    def _validate(self) -> None:
        """Raise ValueError for physically nonsensical constraint combinations."""
        if self.boundary_setback_m < 0:
            raise ValueError("boundary_setback_m must be ≥ 0.")
        if self.inter_panel_gap_m < 0:
            raise ValueError("inter_panel_gap_m must be ≥ 0.")
        if self.inter_column_gap_m < 0:
            raise ValueError("inter_column_gap_m must be ≥ 0.")
        if self.inter_row_spacing_m <= self.panel_h:
            raise ValueError(
                f"inter_row_spacing_m ({self.inter_row_spacing_m:.3f}) must be "
                f"greater than panel height ({self.panel_h:.3f})."
            )
        if self.utility_corridor_width_m < 0:
            raise ValueError("utility_corridor_width_m must be ≥ 0.")

    # ------------------------------------------------------------------
    # Public convenience properties
    # ------------------------------------------------------------------

    @property
    def row_pitch_m(self) -> float:
        """
        Distance from the bottom edge of one row to the bottom edge of the
        next row (Y-axis pitch).

        Equal to inter_row_spacing_m (which already embeds the panel height
        plus shadow/access gap).
        """
        return self.inter_row_spacing_m

    @property
    def column_pitch_m(self) -> float:
        """
        Distance from the left edge of one panel to the left edge of the
        next panel in the same row.

        Equals panel width + inter-panel gap.
        """
        return self.panel_w + self.inter_panel_gap_m

    @property
    def string_pitch_m(self) -> float:
        """
        If panels_per_string > 0, the X-distance between the starts of
        adjacent strings (i.e. a group of panels_per_string panels followed
        by a column gap).

        Returns column_pitch_m when panels_per_string == 0 (unrestricted).
        """
        if self.panels_per_string <= 0:
            return self.column_pitch_m
        return (
            self.panels_per_string * self.column_pitch_m
            + self.inter_column_gap_m
        )

    def __str__(self) -> str:
        return (
            f"SpacingRules("
            f"orientation={self.orientation}, "
            f"panel={self.panel_w:.3f}×{self.panel_h:.3f} m, "
            f"setback={self.boundary_setback_m:.1f} m, "
            f"row_pitch={self.row_pitch_m:.2f} m, "
            f"col_pitch={self.column_pitch_m:.3f} m"
            f")"
        )


# ---------------------------------------------------------------------------
# Usable area computation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UsableAreaResult:
    """
    The outcome of the usable-area calculation step.

    Attributes
    ----------
    usable_polygon:
        Shapely Polygon representing the usable land area after all setbacks
        and reserved corridors have been applied.
    total_area_m2:
        Area of the original land boundary polygon (m²).
    usable_area_m2:
        Area of the usable polygon (m²).
    setback_loss_m2:
        Area consumed by the boundary setback (m²).
    corridor_loss_m2:
        Area consumed by the utility corridor, if any (m²).
    is_viable:
        True when usable_area_m2 ≥ MIN_USABLE_AREA_M2.
    """

    usable_polygon: Polygon
    total_area_m2: float
    usable_area_m2: float
    setback_loss_m2: float
    corridor_loss_m2: float
    is_viable: bool

    @property
    def usable_fraction(self) -> float:
        """Fraction of total area that is usable (0–1)."""
        if self.total_area_m2 <= 0:
            return 0.0
        return self.usable_area_m2 / self.total_area_m2


def compute_usable_area(
    land_polygon: Polygon,
    rules: SpacingRules,
) -> UsableAreaResult:
    """
    Apply boundary setback and utility corridor to derive the usable area.

    Parameters
    ----------
    land_polygon:
        The original land boundary polygon (projected CRS, metres).
    rules:
        Engineering constraints including setback and corridor width.

    Returns
    -------
    UsableAreaResult
        Contains both the usable Shapely Polygon and the area breakdown.

    Raises
    ------
    ValueError
        When the setback consumes the entire polygon.
    """
    total_area = polygon_area_m2(land_polygon)
    logger.info("Total land area: %.4f m².", total_area)

    # Step 1: apply boundary setback
    after_setback = apply_setback(land_polygon, rules.boundary_setback_m)
    if after_setback is None:
        raise ValueError(
            f"Boundary setback of {rules.boundary_setback_m:.2f} m is larger "
            f"than the land parcel. Reduce the setback and try again."
        )

    after_setback_area = polygon_area_m2(after_setback)
    setback_loss = total_area - after_setback_area
    logger.info(
        "After setback (%.2f m): %.4f m² (loss %.4f m²).",
        rules.boundary_setback_m,
        after_setback_area,
        setback_loss,
    )

    # Step 2: carve utility corridor (optional)
    if rules.utility_corridor_width_m > 0:
        after_corridor = apply_utility_corridor(
            after_setback, rules.utility_corridor_width_m, side="south"
        )
        corridor_loss = after_setback_area - polygon_area_m2(after_corridor)
    else:
        after_corridor = after_setback
        corridor_loss = 0.0

    usable_area = polygon_area_m2(after_corridor)
    is_viable = usable_area >= MIN_USABLE_AREA_M2

    if not is_viable:
        logger.warning(
            "Usable area %.4f m² is below the minimum threshold %.4f m².",
            usable_area,
            MIN_USABLE_AREA_M2,
        )

    logger.info(
        "Usable area: %.4f m² (%.1f %% of total, viable=%s).",
        usable_area,
        100.0 * usable_area / total_area if total_area > 0 else 0.0,
        is_viable,
    )

    return UsableAreaResult(
        usable_polygon=after_corridor,
        total_area_m2=total_area,
        usable_area_m2=usable_area,
        setback_loss_m2=setback_loss,
        corridor_loss_m2=corridor_loss,
        is_viable=is_viable,
    )
