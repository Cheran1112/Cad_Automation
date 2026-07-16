"""
solar_layout/panel_optimizer.py
--------------------------------
Row/column grid placement algorithm for arbitrary land polygons.

Single responsibility: given a usable-area polygon and spacing rules,
compute the maximum set of non-overlapping solar panel rectangles that fit
entirely inside the polygon.

Algorithm
---------
A south-to-north, west-to-east raster scan is used:

1. Start at the south-west corner of the bounding box.
2. Walk north one row at a time with a step of ``row_pitch_m``.
3. Within each row walk east one panel at a time with a step of
   ``column_pitch_m`` (or ``string_pitch_m`` when strings are configured).
4. For every candidate position build the panel rectangle and test whether
   it lies entirely within the usable polygon via Shapely ``contains``.
5. Accepted panel rectangles are accumulated.

This approach handles any convex or concave polygon (including L-shapes,
triangles, and other irregular land parcels) without requiring a
computationally expensive optimisation pass.

A future AI optimisation pass can improve on this greedy result by trying
rotated grids, staggered rows, or multi-orientation strategies, all without
changing this module's interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shapely.geometry import Polygon

from solar_layout.geometry_utils import (
    is_panel_inside,
    panel_rect_polygon,
    polygon_bbox,
)
from solar_layout.spacing_rules import SpacingRules

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PanelPlacementResult:
    """
    The outcome of one panel placement run.

    Attributes
    ----------
    panels:
        List of Shapely Polygons, one per placed panel (south-west origin,
        axis-aligned rectangles in the same projected CRS as the boundary).
    panel_count:
        Total number of panels placed.
    total_panel_area_m2:
        Combined area of all placed panels (m²).
    rows_placed:
        Number of rows that contain at least one panel.
    orientation:
        The orientation used for this placement (``'portrait'`` / ``'landscape'``).
    panel_w:
        Panel width (east-west) used (metres).
    panel_h:
        Panel height (north-south) used (metres).
    """

    panels: list[Polygon] = field(default_factory=list)
    panel_count: int = 0
    total_panel_area_m2: float = 0.0
    rows_placed: int = 0
    orientation: str = ""
    panel_w: float = 0.0
    panel_h: float = 0.0

    def __str__(self) -> str:
        return (
            f"PanelPlacementResult("
            f"count={self.panel_count}, "
            f"rows={self.rows_placed}, "
            f"orientation={self.orientation}, "
            f"panel={self.panel_w:.3f}×{self.panel_h:.3f} m, "
            f"total_area={self.total_panel_area_m2:.2f} m²"
            f")"
        )


# ---------------------------------------------------------------------------
# Core placement engine
# ---------------------------------------------------------------------------

def _scan_row(
    row_y: float,
    bbox_min_x: float,
    bbox_max_x: float,
    usable_polygon: Polygon,
    rules: SpacingRules,
) -> list[Polygon]:
    """
    Place panels along a single east-west row at a given northing *row_y*.

    Parameters
    ----------
    row_y:
        Southing (bottom edge) of this row (metres).
    bbox_min_x:
        Western start of the bounding box scan (metres).
    bbox_max_x:
        Eastern limit of the bounding box scan (metres).
    usable_polygon:
        The usable-area polygon; panels must lie entirely inside.
    rules:
        Engineering spacing constraints.

    Returns
    -------
    list of shapely.geometry.Polygon
        Accepted panel rectangles for this row.
    """
    accepted: list[Polygon] = []
    col_x = bbox_min_x

    # When strings are configured, add the inter-column gap after every
    # panels_per_string panels; otherwise just use column_pitch uniformly.
    panels_in_current_string = 0

    while col_x + rules.panel_w <= bbox_max_x + rules.panel_w:
        rect = panel_rect_polygon(col_x, row_y, rules.panel_w, rules.panel_h)

        if is_panel_inside(rect, usable_polygon):
            accepted.append(rect)
            panels_in_current_string += 1

            # Advance: check whether we need a string gap
            if (
                rules.panels_per_string > 0
                and panels_in_current_string >= rules.panels_per_string
            ):
                col_x += rules.panel_w + rules.inter_column_gap_m
                panels_in_current_string = 0
            else:
                col_x += rules.column_pitch_m
        else:
            # Panel does not fit; advance by one column pitch and try next
            col_x += rules.column_pitch_m

        # Safety: stop if we have scanned well past the eastern boundary
        if col_x > bbox_max_x + rules.panel_w:
            break

    return accepted


def place_panels(
    usable_polygon: Polygon,
    rules: SpacingRules,
) -> PanelPlacementResult:
    """
    Maximise the number of solar panels placed inside *usable_polygon*.

    Uses the south-to-north, west-to-east raster scan described in the
    module docstring.

    Parameters
    ----------
    usable_polygon:
        The usable area after boundary setback and corridor carve-out.
    rules:
        Engineering spacing constraints (panel size, row pitch, etc.).

    Returns
    -------
    PanelPlacementResult
        Contains every placed panel rectangle and summary statistics.
    """
    min_x, min_y, max_x, max_y = polygon_bbox(usable_polygon)

    logger.info(
        "Starting panel placement: bbox=(%.2f,%.2f)–(%.2f,%.2f), "
        "panel=%.3f×%.3f m, row_pitch=%.3f m, col_pitch=%.3f m.",
        min_x, min_y, max_x, max_y,
        rules.panel_w, rules.panel_h,
        rules.row_pitch_m, rules.column_pitch_m,
    )

    all_panels: list[Polygon] = []
    rows_placed = 0

    row_y = min_y  # start from the southern edge of the usable bbox

    while row_y + rules.panel_h <= max_y + rules.panel_h:
        row_panels = _scan_row(
            row_y=row_y,
            bbox_min_x=min_x,
            bbox_max_x=max_x,
            usable_polygon=usable_polygon,
            rules=rules,
        )

        if row_panels:
            all_panels.extend(row_panels)
            rows_placed += 1

        row_y += rules.row_pitch_m

        # Safety: stop if we have scanned past the northern boundary
        if row_y > max_y + rules.panel_h:
            break

    total_panel_area = sum(p.area for p in all_panels)

    result = PanelPlacementResult(
        panels=all_panels,
        panel_count=len(all_panels),
        total_panel_area_m2=total_panel_area,
        rows_placed=rows_placed,
        orientation=rules.orientation,
        panel_w=rules.panel_w,
        panel_h=rules.panel_h,
    )

    logger.info(
        "Placement complete: %d panels in %d rows (%.2f m² panel area).",
        result.panel_count,
        result.rows_placed,
        result.total_panel_area_m2,
    )

    return result


# ---------------------------------------------------------------------------
# Multi-orientation comparison
# ---------------------------------------------------------------------------

def optimise_orientation(
    usable_polygon: Polygon,
    portrait_rules: SpacingRules,
    landscape_rules: SpacingRules,
) -> tuple[PanelPlacementResult, str]:
    """
    Run placement for both portrait and landscape orientations and return
    the result that yields more panels.

    Parameters
    ----------
    usable_polygon:
        The usable area polygon.
    portrait_rules:
        SpacingRules configured for portrait orientation.
    landscape_rules:
        SpacingRules configured for landscape orientation.

    Returns
    -------
    tuple[PanelPlacementResult, str]
        The winning placement result and the winning orientation string.
    """
    portrait_result = place_panels(usable_polygon, portrait_rules)
    landscape_result = place_panels(usable_polygon, landscape_rules)

    logger.info(
        "Orientation comparison → portrait: %d panels, landscape: %d panels.",
        portrait_result.panel_count,
        landscape_result.panel_count,
    )

    if landscape_result.panel_count > portrait_result.panel_count:
        return landscape_result, "landscape"
    return portrait_result, "portrait"
