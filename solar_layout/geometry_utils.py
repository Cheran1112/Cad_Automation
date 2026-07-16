"""
solar_layout/geometry_utils.py
-------------------------------
Shapely-based polygon helpers for the Solar Layout Planning module.

Single responsibility: all geometry primitives needed by the solar module.
No panel logic, no DXF, no UI.

The coordinate space is the same projected CRS (metres) that the existing
CAD module uses — Easting on the X-axis, Northing on the Y-axis.
"""

from __future__ import annotations

import logging
from typing import Sequence

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from solar_layout.config import BUFFER_RESOLUTION, GEOMETRY_TOLERANCE_M

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
Coords2D = list[tuple[float, float]]


# ---------------------------------------------------------------------------
# Polygon construction
# ---------------------------------------------------------------------------

def coords_to_polygon(coords: Coords2D) -> Polygon:
    """
    Build a Shapely :class:`~shapely.geometry.Polygon` from an ordered list
    of ``(easting, northing)`` tuples.

    The ring does **not** need to be explicitly closed — Shapely closes it
    automatically.  If the resulting geometry is invalid (self-intersecting,
    etc.) it is repaired with :func:`shapely.validation.make_valid`.

    Parameters
    ----------
    coords:
        At least 3 ``(easting, northing)`` vertex pairs.

    Returns
    -------
    shapely.geometry.Polygon
        A valid, oriented polygon.

    Raises
    ------
    ValueError
        When fewer than 3 coordinate pairs are supplied.
    """
    if len(coords) < 3:
        raise ValueError(
            f"A polygon requires at least 3 coordinate pairs; {len(coords)} given."
        )

    poly = Polygon(coords)

    if not poly.is_valid:
        logger.warning(
            "Input polygon is invalid (%s). Attempting repair via make_valid.",
            poly.geom_type,
        )
        poly = make_valid(poly)
        # make_valid may return a MultiPolygon or GeometryCollection; take the
        # largest Polygon part.
        poly = _largest_polygon(poly)

    # Ensure counter-clockwise exterior orientation (Shapely convention)
    if not poly.exterior.is_ccw:
        poly = poly.reverse()

    logger.debug(
        "coords_to_polygon: %d vertices → area=%.4f m².", len(coords), poly.area
    )
    return poly


def _largest_polygon(geom) -> Polygon:
    """
    Extract the largest Polygon from a geometry that may be a
    MultiPolygon, GeometryCollection, or Polygon.

    Parameters
    ----------
    geom:
        Any Shapely geometry.

    Returns
    -------
    shapely.geometry.Polygon
    """
    if geom.geom_type == "Polygon":
        return geom
    # Flatten to individual polygons and pick by area
    parts: list[Polygon] = []
    if hasattr(geom, "geoms"):
        for g in geom.geoms:
            if g.geom_type == "Polygon":
                parts.append(g)
            elif hasattr(g, "geoms"):
                parts.extend(
                    p for p in g.geoms if p.geom_type == "Polygon"
                )
    if not parts:
        raise ValueError("make_valid produced no usable Polygon geometry.")
    return max(parts, key=lambda p: p.area)


# ---------------------------------------------------------------------------
# Setback / erosion
# ---------------------------------------------------------------------------

def apply_setback(polygon: Polygon, setback_m: float) -> Polygon | None:
    """
    Erode *polygon* inward by *setback_m* metres to produce the usable area.

    A negative buffer (inward offset) is used.  If the result is empty or
    collapses below a usable threshold, ``None`` is returned so callers can
    detect and report the failure gracefully.

    Parameters
    ----------
    polygon:
        The land boundary polygon (projected CRS, metres).
    setback_m:
        Distance to erode inward (metres).  Must be ≥ 0.

    Returns
    -------
    shapely.geometry.Polygon or None
        The eroded polygon, or ``None`` when erosion consumes the entire area.
    """
    if setback_m <= 0.0:
        return polygon

    eroded = polygon.buffer(
        -setback_m,
        resolution=BUFFER_RESOLUTION,
        join_style=2,   # mitre join – preserves corners cleanly
    )

    if eroded.is_empty or eroded.area < GEOMETRY_TOLERANCE_M ** 2:
        logger.warning(
            "Setback of %.2f m consumed the entire polygon (area=%.4f m²).",
            setback_m,
            polygon.area,
        )
        return None

    # make_valid in case the buffer produces degeneracies
    if not eroded.is_valid:
        eroded = make_valid(eroded)

    # If result is MultiPolygon, keep the largest piece
    if eroded.geom_type != "Polygon":
        eroded = _largest_polygon(eroded)

    logger.debug(
        "Setback %.2f m: %.4f m² → %.4f m² (retained %.1f %%).",
        setback_m,
        polygon.area,
        eroded.area,
        100.0 * eroded.area / polygon.area if polygon.area > 0 else 0.0,
    )
    return eroded


def apply_utility_corridor(
    polygon: Polygon,
    corridor_width_m: float,
    side: str = "south",
) -> Polygon:
    """
    Carve a utility corridor out of the southern (or any) edge of *polygon*.

    The corridor is cut by subtracting a horizontal strip of
    *corridor_width_m* from the requested edge.  If *corridor_width_m* is
    zero or negative the original polygon is returned unchanged.

    Parameters
    ----------
    polygon:
        Usable area polygon after boundary setback.
    corridor_width_m:
        Width of the reserved utility strip (metres).
    side:
        Which edge to cut: ``'south'``, ``'north'``, ``'east'``, or ``'west'``.

    Returns
    -------
    shapely.geometry.Polygon
        Polygon with the corridor removed.
    """
    if corridor_width_m <= 0.0:
        return polygon

    from shapely.geometry import box

    minx, miny, maxx, maxy = polygon.bounds

    corridor_strips = {
        "south": box(minx - 1, miny - 1, maxx + 1, miny + corridor_width_m),
        "north": box(minx - 1, maxy - corridor_width_m, maxx + 1, maxy + 1),
        "west":  box(minx - 1, miny - 1, minx + corridor_width_m, maxy + 1),
        "east":  box(maxx - corridor_width_m, miny - 1, maxx + 1, maxy + 1),
    }
    strip = corridor_strips.get(side.lower())
    if strip is None:
        logger.warning("Unknown corridor side '%s'; skipping corridor cut.", side)
        return polygon

    result = polygon.difference(strip)
    if result.is_empty:
        logger.warning(
            "Corridor of %.2f m on '%s' side consumed entire polygon.", corridor_width_m, side
        )
        return polygon

    if result.geom_type != "Polygon":
        result = _largest_polygon(result)

    return result


# ---------------------------------------------------------------------------
# Panel-boundary containment test
# ---------------------------------------------------------------------------

def panel_rect_polygon(
    origin_x: float,
    origin_y: float,
    panel_w: float,
    panel_h: float,
) -> Polygon:
    """
    Build a rectangular Shapely Polygon representing a single solar panel.

    The origin is the **south-west (lower-left)** corner of the panel.

    Parameters
    ----------
    origin_x:
        Easting of the south-west corner (metres).
    origin_y:
        Northing of the south-west corner (metres).
    panel_w:
        Panel width in the easting (X) direction (metres).
    panel_h:
        Panel height in the northing (Y) direction (metres).

    Returns
    -------
    shapely.geometry.Polygon
        Axis-aligned rectangle.
    """
    from shapely.geometry import box
    return box(origin_x, origin_y, origin_x + panel_w, origin_y + panel_h)


def is_panel_inside(
    panel_poly: Polygon,
    boundary: Polygon,
    tolerance: float = GEOMETRY_TOLERANCE_M,
) -> bool:
    """
    Return ``True`` when *panel_poly* lies entirely within *boundary*.

    A small negative tolerance is applied to the boundary before testing so
    panels that touch the boundary edge due to floating-point rounding are
    still accepted.

    Parameters
    ----------
    panel_poly:
        Rectangle produced by :func:`panel_rect_polygon`.
    boundary:
        Usable-area polygon (after setback).
    tolerance:
        Permissible overhang in metres (default: sub-millimetre).

    Returns
    -------
    bool
    """
    # Use a tiny inward-buffered boundary to absorb floating-point errors
    test_boundary = boundary.buffer(tolerance)
    return test_boundary.contains(panel_poly)


# ---------------------------------------------------------------------------
# Bounding-box helpers
# ---------------------------------------------------------------------------

def polygon_bbox(polygon: Polygon) -> tuple[float, float, float, float]:
    """
    Return the axis-aligned bounding box of *polygon*.

    Returns
    -------
    tuple
        ``(min_easting, min_northing, max_easting, max_northing)``
    """
    minx, miny, maxx, maxy = polygon.bounds
    return minx, miny, maxx, maxy


def polygon_area_m2(polygon: Polygon) -> float:
    """
    Return the area of *polygon* in square metres.

    Parameters
    ----------
    polygon:
        A Shapely Polygon in a projected CRS where coordinates are in metres.
    """
    return float(polygon.area)


# ---------------------------------------------------------------------------
# Coordinate extraction
# ---------------------------------------------------------------------------

def polygon_exterior_coords(polygon: Polygon) -> Coords2D:
    """
    Extract the exterior ring coordinates as a list of ``(x, y)`` tuples.

    The returned list does **not** repeat the first vertex.

    Parameters
    ----------
    polygon:
        Source polygon.

    Returns
    -------
    list of (float, float)
    """
    coords = list(polygon.exterior.coords)
    # Shapely closes the ring by repeating the first point; remove the duplicate
    if coords and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [(float(x), float(y)) for x, y in coords]
