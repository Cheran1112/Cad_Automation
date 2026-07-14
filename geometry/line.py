"""
geometry/line.py
----------------
Defines the Line segment that connects two consecutive survey points.

Single responsibility: represent a directed line segment and expose
basic measurements (length, midpoint, bearing).
No polygon logic, no I/O, no UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from geometry.point import Point


@dataclass(frozen=True)
class Line:
    """
    A directed line segment from *start* to *end*.

    Attributes
    ----------
    start:
        Origin point.
    end:
        Destination point.
    """

    start: Point
    end: Point

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Line({self.start.point_id!r} → {self.end.point_id!r}, len={self.length:.3f})"

    # ------------------------------------------------------------------
    # Measurements
    # ------------------------------------------------------------------

    @property
    def length(self) -> float:
        """Euclidean length of the segment in coordinate units."""
        return self.start.distance_to(self.end)

    @property
    def midpoint(self) -> tuple[float, float]:
        """
        Arithmetic midpoint of the segment.

        Returns
        -------
        tuple[float, float]
            ``(easting, northing)`` of the midpoint.
        """
        return (
            (self.start.easting + self.end.easting) / 2.0,
            (self.start.northing + self.end.northing) / 2.0,
        )

    @property
    def bearing_degrees(self) -> float:
        """
        Whole-circle bearing from *start* to *end*, measured clockwise
        from grid north (positive Y-axis), in degrees [0, 360).

        Returns
        -------
        float
            Bearing in degrees.
        """
        delta_e = self.end.easting - self.start.easting
        delta_n = self.end.northing - self.start.northing
        angle = math.degrees(math.atan2(delta_e, delta_n))
        return angle % 360.0

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def as_tuple_pair(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """
        Return the segment as a pair of ``(easting, northing)`` tuples,
        suitable for use with matplotlib or ezdxf.

        Returns
        -------
        tuple
            ``((e_start, n_start), (e_end, n_end))``
        """
        return (self.start.as_tuple(), self.end.as_tuple())
