"""
validation/validator.py
-----------------------
Responsible for all data-quality checks on the normalised survey DataFrame.

Single responsibility: validation only.
No geometry calculations, no UI, no file I/O.

Checks performed
----------------
1.  Required columns present          (structural – caught by reader, re-confirmed here)
2.  Minimum point count               (>= MIN_POINTS)
3.  Missing / NaN values              (Point_ID, Easting, Northing)
4.  Invalid numeric values            (non-finite: inf, -inf)
5.  Duplicate Point IDs
6.  Duplicate coordinates             (within COORD_TOLERANCE)
7.  Polygon closure feasibility       (need >= 3 unique points)
8.  Self-intersection detection       (via Shapely)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List

import pandas as pd
from shapely.geometry import LinearRing
from shapely.validation import explain_validity

from config import (
    COL_EASTING,
    COL_NORTHING,
    COL_POINT_ID,
    COORD_TOLERANCE,
    MIN_POINTS,
    REQUIRED_COLUMNS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """A single validation problem with its severity and a human-readable message."""

    severity: str   # "error" | "warning"
    code: str       # machine-readable short code
    message: str    # full description shown in the UI
    rows: List[int] = field(default_factory=list)  # 0-based row indices (if applicable)

    def __str__(self) -> str:
        row_info = f" (rows: {self.rows})" if self.rows else ""
        return f"[{self.severity.upper()}] {self.code}: {self.message}{row_info}"


@dataclass
class ValidationResult:
    """Aggregated outcome of running all checks."""

    issues: List[ValidationIssue] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def errors(self) -> List[ValidationIssue]:
        """All issues with severity == 'error'."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """All issues with severity == 'warning'."""
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        """True when there are no errors (warnings are allowed)."""
        return len(self.errors) == 0

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def add_error(self, code: str, message: str, rows: List[int] | None = None) -> None:
        self.issues.append(
            ValidationIssue(severity="error", code=code, message=message, rows=rows or [])
        )

    def add_warning(self, code: str, message: str, rows: List[int] | None = None) -> None:
        self.issues.append(
            ValidationIssue(severity="warning", code=code, message=message, rows=rows or [])
        )

    def summary(self) -> str:
        """One-line human-readable summary."""
        if self.is_valid:
            warn_part = f" with {self.warning_count} warning(s)" if self.warnings else ""
            return f"Validation passed{warn_part}."
        return (
            f"Validation failed: {self.error_count} error(s), "
            f"{self.warning_count} warning(s)."
        )


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def _check_required_columns(df: pd.DataFrame, result: ValidationResult) -> bool:
    """
    Confirm all required columns are present.

    Returns True if the check passes (allowing subsequent checks to proceed).
    If columns are missing the remaining checks cannot run safely so we
    return False to signal early exit.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        result.add_error(
            code="MISSING_COLUMNS",
            message=f"Required column(s) missing: {missing}. "
                    f"Expected: {REQUIRED_COLUMNS}.",
        )
        return False
    return True


def _check_minimum_points(df: pd.DataFrame, result: ValidationResult) -> bool:
    """Dataset must have at least MIN_POINTS rows to form a polygon."""
    if len(df) < MIN_POINTS:
        result.add_error(
            code="INSUFFICIENT_POINTS",
            message=(
                f"At least {MIN_POINTS} points are required to form a polygon. "
                f"Only {len(df)} point(s) found."
            ),
        )
        return False
    return True


def _check_missing_values(df: pd.DataFrame, result: ValidationResult) -> None:
    """Detect NaN cells in any of the three required columns."""
    for col in REQUIRED_COLUMNS:
        null_mask = df[col].isnull()
        if null_mask.any():
            bad_rows: list[int] = null_mask[null_mask].index.tolist()
            result.add_error(
                code="MISSING_VALUES",
                message=(
                    f"Column '{col}' has {null_mask.sum()} missing value(s). "
                    f"Affected rows (0-based): {bad_rows}."
                ),
                rows=bad_rows,
            )


def _check_invalid_numeric(df: pd.DataFrame, result: ValidationResult) -> None:
    """Detect infinity or non-finite values in Easting / Northing."""
    for col in (COL_EASTING, COL_NORTHING):
        # Only check rows where the value is not already NaN
        not_null = df[col].dropna()
        inf_mask = not_null.apply(lambda v: math.isinf(float(v)) if pd.notna(v) else False)
        if inf_mask.any():
            bad_rows = inf_mask[inf_mask].index.tolist()
            result.add_error(
                code="INVALID_NUMERIC",
                message=(
                    f"Column '{col}' contains infinite value(s) at row(s): {bad_rows}."
                ),
                rows=bad_rows,
            )


def _check_duplicate_ids(df: pd.DataFrame, result: ValidationResult) -> None:
    """Detect repeated Point_ID values."""
    dup_mask = df[COL_POINT_ID].duplicated(keep=False)
    if dup_mask.any():
        dup_ids = df.loc[dup_mask, COL_POINT_ID].unique().tolist()
        bad_rows = dup_mask[dup_mask].index.tolist()
        result.add_error(
            code="DUPLICATE_POINT_IDS",
            message=(
                f"Duplicate Point_ID value(s) found: {dup_ids}. "
                f"Affected rows (0-based): {bad_rows}."
            ),
            rows=bad_rows,
        )


def _check_duplicate_coordinates(df: pd.DataFrame, result: ValidationResult) -> None:
    """
    Detect points whose (Easting, Northing) pair is effectively identical
    within COORD_TOLERANCE.

    Strategy: round both coordinates to the precision implied by
    COORD_TOLERANCE, then look for duplicates on the rounded values.
    """
    # Number of decimal places corresponding to tolerance
    decimals = max(0, -int(math.floor(math.log10(COORD_TOLERANCE))))

    clean = df[[COL_EASTING, COL_NORTHING]].dropna()
    rounded = clean.round(decimals)
    dup_mask = rounded.duplicated(keep=False)

    if dup_mask.any():
        bad_rows = dup_mask[dup_mask].index.tolist()
        result.add_error(
            code="DUPLICATE_COORDINATES",
            message=(
                f"{dup_mask.sum()} point(s) share the same coordinates "
                f"(within tolerance {COORD_TOLERANCE}). "
                f"Affected rows (0-based): {bad_rows}."
            ),
            rows=bad_rows,
        )


def _check_self_intersection(df: pd.DataFrame, result: ValidationResult) -> None:
    """
    Build a Shapely LinearRing from the point sequence and check for
    self-intersections.

    Requires that the DataFrame has no NaN coordinates; call after
    _check_missing_values has already flagged any nulls.
    """
    clean = df[[COL_EASTING, COL_NORTHING]].dropna()
    if len(clean) < MIN_POINTS:
        # Cannot build ring – insufficient clean points; already caught above.
        return

    coords = list(zip(clean[COL_EASTING].tolist(), clean[COL_NORTHING].tolist()))

    # Close ring if not already closed
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    try:
        ring = LinearRing(coords)
    except Exception as exc:  # noqa: BLE001
        result.add_warning(
            code="RING_BUILD_FAILED",
            message=f"Could not build polygon ring for self-intersection check: {exc}",
        )
        return

    if not ring.is_simple:
        explanation = explain_validity(ring)
        result.add_error(
            code="SELF_INTERSECTION",
            message=(
                f"The boundary polygon self-intersects. "
                f"Shapely reports: '{explanation}'. "
                "Review the point sequence or coordinate values."
            ),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(df: pd.DataFrame) -> ValidationResult:
    """
    Run all validation checks on a normalised survey DataFrame.

    Parameters
    ----------
    df:
        DataFrame returned by :func:`data.reader.read_file`.

    Returns
    -------
    ValidationResult
        Contains a list of :class:`ValidationIssue` objects.
        Use ``result.is_valid`` to decide whether to proceed.
    """
    result = ValidationResult()

    # Gate 1 – columns must exist before anything else
    if not _check_required_columns(df, result):
        logger.warning("Column check failed – skipping remaining validation.")
        return result

    # Gate 2 – need enough points before checks that iterate rows
    if not _check_minimum_points(df, result):
        logger.warning("Point count check failed – skipping remaining validation.")
        return result

    # Independent per-cell checks
    _check_missing_values(df, result)
    _check_invalid_numeric(df, result)
    _check_duplicate_ids(df, result)
    _check_duplicate_coordinates(df, result)

    # Geometry-level check (only if no hard errors so far to avoid noise)
    if result.is_valid:
        _check_self_intersection(df, result)

    status = "PASSED" if result.is_valid else "FAILED"
    logger.info(
        "Validation %s – %d error(s), %d warning(s).",
        status,
        result.error_count,
        result.warning_count,
    )

    return result
