"""
preview/plotter.py
------------------
Responsible for rendering the survey boundary as a Matplotlib figure.

Single responsibility: produce a Figure object from geometry primitives.
No file I/O, no validation, no Streamlit calls.
The caller (app.py) decides how to display or embed the figure.

Design notes
------------
* Returns a ``matplotlib.figure.Figure`` so the caller controls the lifecycle.
* Uses equal-axis scaling so real-world shapes are not distorted.
* Adds a configurable margin around the bounding box so points on the
  edge are never clipped.
* All style constants are imported from config.py.
"""

from __future__ import annotations

import logging

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.figure import Figure

from config import (
    PREVIEW_DPI,
    PREVIEW_FIG_SIZE,
    PREVIEW_LABEL_COLOR,
    PREVIEW_LABEL_FONTSIZE,
    PREVIEW_LINE_COLOR,
    PREVIEW_POINT_COLOR,
    PREVIEW_POINT_SIZE,
)
from geometry.calculator import GeometryMetrics
from geometry.polyline import Polyline

logger = logging.getLogger(__name__)

# Fractional padding added around the bounding box (5 % each side)
_BBOX_MARGIN_FRACTION: float = 0.05


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_axis_limits(
    metrics: GeometryMetrics,
    margin_fraction: float = _BBOX_MARGIN_FRACTION,
) -> tuple[float, float, float, float]:
    """
    Compute padded axis limits that keep all geometry comfortably inside
    the plot area.

    Parameters
    ----------
    metrics:
        Pre-computed geometry metrics.
    margin_fraction:
        Fraction of the larger bounding-box dimension to add as padding
        on each side.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x_min, x_max, y_min, y_max)``
    """
    span = max(metrics.bbox_width, metrics.bbox_height)
    margin = span * margin_fraction if span > 0 else 1.0

    return (
        metrics.bbox_min_easting - margin,
        metrics.bbox_max_easting + margin,
        metrics.bbox_min_northing - margin,
        metrics.bbox_max_northing + margin,
    )


def _draw_boundary(ax: plt.Axes, polyline: Polyline) -> None:
    """
    Plot the closed boundary polyline.

    Parameters
    ----------
    ax:
        Target Matplotlib axes.
    polyline:
        Survey boundary object.
    """
    closed = polyline.closed_coordinates          # includes repeat of first point
    xs = [c[0] for c in closed]
    ys = [c[1] for c in closed]

    ax.plot(
        xs,
        ys,
        color=PREVIEW_LINE_COLOR,
        linewidth=1.5,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=2,
        label="Survey Boundary",
    )


def _draw_points(ax: plt.Axes, polyline: Polyline) -> None:
    """
    Plot a marker at each survey vertex.

    Parameters
    ----------
    ax:
        Target Matplotlib axes.
    polyline:
        Survey boundary object.
    """
    xs = [p.easting for p in polyline.points]
    ys = [p.northing for p in polyline.points]

    ax.scatter(
        xs,
        ys,
        color=PREVIEW_POINT_COLOR,
        s=PREVIEW_POINT_SIZE ** 2,   # scatter uses area, not radius
        zorder=3,
        label="Survey Points",
    )


def _draw_labels(ax: plt.Axes, polyline: Polyline, metrics: GeometryMetrics) -> None:
    """
    Annotate each vertex with its Point_ID.

    The label is nudged a small fraction of the bounding-box diagonal to
    the upper-right so it does not overwrite the point marker.

    Parameters
    ----------
    ax:
        Target Matplotlib axes.
    polyline:
        Survey boundary object.
    metrics:
        Pre-computed geometry metrics used to compute label offset.
    """
    diagonal = (metrics.bbox_width ** 2 + metrics.bbox_height ** 2) ** 0.5
    offset = diagonal * 0.008 if diagonal > 0 else 0.5

    for pt in polyline.points:
        ax.annotate(
            text=pt.point_id,
            xy=(pt.easting, pt.northing),
            xytext=(pt.easting + offset, pt.northing + offset),
            fontsize=PREVIEW_LABEL_FONTSIZE,
            color=PREVIEW_LABEL_COLOR,
            ha="left",
            va="bottom",
            zorder=4,
        )


def _draw_centroid(ax: plt.Axes, metrics: GeometryMetrics) -> None:
    """
    Mark the polygon centroid with a cross-hair marker.

    Parameters
    ----------
    ax:
        Target Matplotlib axes.
    metrics:
        Pre-computed geometry metrics.
    """
    ax.plot(
        metrics.centroid_easting,
        metrics.centroid_northing,
        marker="+",
        markersize=10,
        color="#8E44AD",   # purple – visually distinct
        markeredgewidth=1.5,
        zorder=5,
        label="Centroid",
    )


def _apply_formatting(
    ax: plt.Axes,
    fig: Figure,
    metrics: GeometryMetrics,
    point_count: int,
) -> None:
    """
    Apply titles, axis labels, grid, legend, and equal scaling.

    Parameters
    ----------
    ax:
        Target Matplotlib axes.
    fig:
        Parent figure (used for the overall title).
    metrics:
        Pre-computed geometry metrics for the info annotation.
    point_count:
        Number of survey vertices.
    """
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.5, color="#AAAAAA")

    ax.set_xlabel("Easting (m)", fontsize=9)
    ax.set_ylabel("Northing (m)", fontsize=9)
    ax.tick_params(axis="both", labelsize=7)

    # Scientific-notation offset on tick labels can obscure real coordinates –
    # force plain formatting
    ax.ticklabel_format(useOffset=False, style="plain")

    fig.suptitle("Survey Boundary Preview", fontsize=12, fontweight="bold", y=0.98)

    # Metrics annotation inside the plot
    info = (
        f"Points: {point_count}   "
        f"Area: {metrics.area_abs:,.2f} m²   "
        f"Perimeter: {metrics.perimeter:,.2f} m"
    )
    ax.set_title(info, fontsize=8, color="#555555", pad=6)

    # Legend (deduplicated)
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(
        by_label.values(),
        by_label.keys(),
        loc="lower right",
        fontsize=7,
        framealpha=0.7,
    )

    fig.tight_layout(rect=[0, 0, 1, 0.97])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_preview_figure(
    polyline: Polyline,
    metrics: GeometryMetrics,
) -> Figure:
    """
    Produce a Matplotlib :class:`~matplotlib.figure.Figure` showing the
    survey boundary with point markers, labels, centroid, and metrics.

    The figure uses equal-axis scaling so the boundary is never distorted.
    Call ``plt.close(fig)`` after the figure is no longer needed to free
    memory.

    Parameters
    ----------
    polyline:
        The closed survey boundary.
    metrics:
        Pre-computed geometry metrics.

    Returns
    -------
    matplotlib.figure.Figure
        Fully composed figure, ready to be embedded in Streamlit via
        ``st.pyplot(fig)`` or saved with ``fig.savefig(...)``.
    """
    fig, ax = plt.subplots(figsize=PREVIEW_FIG_SIZE, dpi=PREVIEW_DPI)

    # Draw layers in z-order: boundary → points → labels → centroid
    _draw_boundary(ax, polyline)
    _draw_points(ax, polyline)
    _draw_labels(ax, polyline, metrics)
    _draw_centroid(ax, metrics)

    # Set padded axis limits before applying equal aspect so autoscale
    # doesn't override our bounding-box calculation
    x_min, x_max, y_min, y_max = _compute_axis_limits(metrics)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)

    _apply_formatting(ax, fig, metrics, polyline.point_count)

    logger.info(
        "Preview figure built: %d points, bbox E[%.2f…%.2f] N[%.2f…%.2f].",
        polyline.point_count,
        metrics.bbox_min_easting,
        metrics.bbox_max_easting,
        metrics.bbox_min_northing,
        metrics.bbox_max_northing,
    )

    return fig
