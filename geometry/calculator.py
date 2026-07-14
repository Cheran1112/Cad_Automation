"""
geometry/calculator.py
----------------------
Pure spatial calculations on a Polyline.

Single responsibility: compute area, perimeter, bounding box, and centroid.
No file I/O, no UI.  All functions are stateless and accept only the
geometric primitives defined in this package.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from geometry.polyline import Polyline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeometryMetrics:
    """
    Computed spatial metrics for a survey boundary polygon.

    Attributes
    ----------
    area:
        Signed area in square coordinate units (positive = counter-clockwise).
        Use :attr:`area_abs` for the unsigned value.
    perimeter:
        Total boundary length in coordinate units.
    bbox_min_easting:
        Western edge of the bounding box.
    bbox_max_easting:
        Eastern edge of the bounding box.
    bbox_min_northing:
        Southern edge of the bounding box.
    bbox_max_northing:
        Northern edge of the bounding box.
    centroid_easting:
        Easting of the polygon centroid.
    centroid_northing:
        Northing of the polygon centroid.
    """

    area: float
    perimeter: float
    bbox_min_easting: float
    bbox_max_easting: float
    bbox_min_northing: float
    bbox_max_northing: float
    centroid_easting: float
    centroid_northing: float

    @property
    def area_abs(self) -> float:
        """Absolute (unsigned) area."""
        return abs(self.area)

    @property
    def bbox_width(self) -> float:
        """East–west extent of the bounding box."""
        return self.bbox_max_easting - self.bbox_min_easting

    @property
    def bbox_height(self) -> float:
        """North–south extent of the bounding box."""
        return self.bbox_max_northing - self.bbox_min_northing

    def __str__(self) -> str:
        return (
            f"Area:      {self.area_abs:,.4f} sq units\n"
            f"Perimeter: {self.perimeter:,.4f} units\n"
            f"Centroid:  E={self.centroid_easting:.4f}, N={self.centroid_northing:.4f}\n"
            f"Bbox:      E[{self.bbox_min_easting:.3f} … {self.bbox_max_easting:.3f}]  "
            f"N[{self.bbox_min_northing:.3f} … {self.bbox_max_northing:.3f}]"
        )


# ---------------------------------------------------------------------------
# Core algorithms
# ---------------------------------------------------------------------------

def _shoelace_area(coords: list[tuple[float, float]]) -> float:
    """
    Compute the signed polygon area using the Shoelace (Gauss) formula.

    Parameters
    ----------
    coords:
        Ordered ``(x, y)`` vertex list.  The polygon is **not** required
        to be explicitly closed (first == last).

    Returns
    -------
    float
        Signed area: positive for counter-clockwise orientation.
    """
    n = len(coords)
    total = 0.0
    for i in range(n):
        x_i, y_i = coords[i]
        x_j, y_j = coords[(i + 1) % n]
        total += (x_i * y_j) - (x_j * y_i)
    return total / 2.0


def _polygon_centroid(
    coords: list[tuple[float, float]], signed_area: float
) -> tuple[float, float]:
    """
    Compute the centroid of a simple polygon.

    Uses the standard centroid formula derived from the Shoelace expansion.

    Parameters
    ----------
    coords:
        Ordered ``(x, y)`` vertex list (not closed).
    signed_area:
        Pre-computed signed area from :func:`_shoelace_area`.

    Returns
    -------
    tuple[float, float]
        ``(cx, cy)`` centroid coordinates.
    """
    if signed_area == 0.0:
        # Degenerate polygon – fall back to arithmetic mean
        cx = sum(x for x, _ in coords) / len(coords)
        cy = sum(y for _, y in coords) / len(coords)
        return cx, cy

    cx = 0.0
    cy = 0.0
    n = len(coords)
    for i in range(n):
        x_i, y_i = coords[i]
        x_j, y_j = coords[(i + 1) % n]
        cross = (x_i * y_j) - (x_j * y_i)
        cx += (x_i + x_j) * cross
        cy += (y_i + y_j) * cross

    factor = 1.0 / (6.0 * signed_area)
    return cx * factor, cy * factor


def _bounding_box(
    coords: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """
    Axis-aligned bounding box.

    Returns
    -------
    tuple
        ``(min_x, max_x, min_y, max_y)``
    """
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    return min(xs), max(xs), min(ys), max(ys)


def _total_perimeter(polyline: Polyline) -> float:
    """Sum of all segment lengths including the closing segment."""
    return sum(seg.length for seg in polyline.segments)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_metrics(polyline: Polyline) -> GeometryMetrics:
    """
    Calculate all spatial metrics for a closed survey boundary.

    Parameters
    ----------
    polyline:
        A fully constructed :class:`~geometry.polyline.Polyline`.

    Returns
    -------
    GeometryMetrics
        Immutable metrics object.

    Notes
    -----
    * Area is computed with the Shoelace formula — exact for simple polygons
      with any number of vertices.
    * Centroid uses the standard polygon centroid formula (not the arithmetic
      mean of vertices, which gives the wrong result for non-uniform spacing).
    * All computations are pure Python / float64; no external libraries needed.
    """
    coords = polyline.coordinates  # list of (E, N), not closed

    signed_area = _shoelace_area(coords)
    cx, cy = _polygon_centroid(coords, signed_area)
    min_e, max_e, min_n, max_n = _bounding_box(coords)
    perimeter = _total_perimeter(polyline)

    metrics = GeometryMetrics(
        area=signed_area,
        perimeter=perimeter,
        bbox_min_easting=min_e,
        bbox_max_easting=max_e,
        bbox_min_northing=min_n,
        bbox_max_northing=max_n,
        centroid_easting=cx,
        centroid_northing=cy,
    )

    logger.info(
        "Geometry metrics: area=%.4f sq-units, perimeter=%.4f units, "
        "centroid=(%.4f, %.4f)",
        metrics.area_abs,
        metrics.perimeter,
        metrics.centroid_easting,
        metrics.centroid_northing,
    )

    return metrics
