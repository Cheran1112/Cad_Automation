"""
geometry/point.py
-----------------
Defines the immutable Point data object.

Single responsibility: represent a single 2-D survey point.
No calculations, no I/O, no UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    """
    An immutable 2-D survey point.

    Attributes
    ----------
    point_id:
        The original survey identifier (e.g. 'B01').
    easting:
        X-coordinate (metres, projected CRS).
    northing:
        Y-coordinate (metres, projected CRS).
    """

    point_id: str
    easting: float
    northing: float

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Point(id={self.point_id!r}, E={self.easting:.3f}, N={self.northing:.3f})"

    # ------------------------------------------------------------------
    # Spatial helpers
    # ------------------------------------------------------------------

    def distance_to(self, other: Point) -> float:
        """
        Euclidean distance between this point and *other*.

        Parameters
        ----------
        other:
            Target point.

        Returns
        -------
        float
            Distance in the same units as the coordinates.
        """
        return math.hypot(self.easting - other.easting, self.northing - other.northing)

    def as_tuple(self) -> tuple[float, float]:
        """Return ``(easting, northing)`` as a plain tuple."""
        return (self.easting, self.northing)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Point:
        """
        Construct a Point from a dictionary with keys
        ``'Point_ID'``, ``'Easting'``, and ``'Northing'``.

        Parameters
        ----------
        data:
            Mapping produced by iterating a survey DataFrame row.

        Returns
        -------
        Point
        """
        return cls(
            point_id=str(data["Point_ID"]),
            easting=float(data["Easting"]),
            northing=float(data["Northing"]),
        )
