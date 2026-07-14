"""
geometry/polyline.py
--------------------
Builds the closed survey boundary polyline from an ordered list of Points.

Single responsibility: assemble points into a closed polygon entity and
expose the ordered coordinate sequence.  All numeric calculations
(area, perimeter, etc.) are delegated to geometry/calculator.py.
No I/O, no UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from geometry.line import Line
from geometry.point import Point

logger = logging.getLogger(__name__)


@dataclass
class Polyline:
    """
    An ordered, closed polygon boundary built from survey points.

    The closing segment (last point → first point) is added automatically
    and is always included in :attr:`segments`.

    Attributes
    ----------
    points:
        Ordered list of :class:`Point` objects as read from the survey file.
    """

    points: list[Point]
    _segments: list[Line] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError(
                f"A polygon requires at least 3 points; {len(self.points)} given."
            )
        self._build_segments()

    # ------------------------------------------------------------------
    # Internal construction
    # ------------------------------------------------------------------

    def _build_segments(self) -> None:
        """Connect consecutive points and close the polygon."""
        self._segments = []
        for i in range(len(self.points)):
            start = self.points[i]
            end = self.points[(i + 1) % len(self.points)]  # wraps to 0 on last iteration
            self._segments.append(Line(start=start, end=end))
        logger.debug("Built %d segment(s) for closed polygon.", len(self._segments))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def segments(self) -> list[Line]:
        """All segments including the closing one."""
        return self._segments

    @property
    def point_count(self) -> int:
        """Number of unique vertices (not counting the implicit closing repeat)."""
        return len(self.points)

    @property
    def coordinates(self) -> list[tuple[float, float]]:
        """
        Ordered ``(easting, northing)`` tuples for all vertices.

        Does **not** repeat the first vertex at the end; callers that
        need a closed ring should append ``coordinates[0]`` themselves.
        """
        return [p.as_tuple() for p in self.points]

    @property
    def closed_coordinates(self) -> list[tuple[float, float]]:
        """
        Ordered ``(easting, northing)`` tuples with the first vertex
        repeated at the end to form an explicitly closed ring.
        """
        coords = self.coordinates
        return coords + [coords[0]]

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> Polyline:
        """
        Build a :class:`Polyline` directly from a normalised survey DataFrame.

        The row order in the DataFrame defines the point sequence.

        Parameters
        ----------
        df:
            DataFrame with columns ``Point_ID``, ``Easting``, ``Northing``
            as returned by :func:`data.reader.read_file`.

        Returns
        -------
        Polyline

        Raises
        ------
        ValueError
            If the DataFrame has fewer than 3 rows.
        """
        points = [Point.from_dict(row) for row in df.to_dict(orient="records")]
        return cls(points=points)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return self.point_count

    def __repr__(self) -> str:
        return (
            f"Polyline(points={self.point_count}, "
            f"segments={len(self._segments)}, closed=True)"
        )
