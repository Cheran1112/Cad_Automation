"""
cad/dxf_generator.py
--------------------
Responsible for generating a professional DXF file from a survey boundary.

Single responsibility: DXF creation only.
No geometry calculations, no validation, no UI.

Output structure
----------------
Layer SURVEY_BOUNDARY  – closed LWPolyline (the boundary)
Layer SURVEY_POINTS    – POINT entities at each vertex
Layer SURVEY_LABELS    – TEXT entities with Point_ID labels

The generated file targets DXF version R2010 (AutoCAD 2010+) for the
widest possible compatibility with older CAD installations.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

import ezdxf
from ezdxf import colors
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment

from config import (
    DEFAULT_DXF_FILENAME,
    DXF_COLOR_BOUNDARY,
    DXF_COLOR_LABELS,
    DXF_COLOR_POINTS,
    DXF_LAYER_BOUNDARY,
    DXF_LAYER_LABELS,
    DXF_LAYER_POINTS,
    DXF_TEXT_HEIGHT,
    DXF_VERSION,
    OUTPUT_DIR,
)
from geometry.calculator import GeometryMetrics
from geometry.polyline import Polyline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _create_document() -> Drawing:
    """
    Create a new DXF document with the configured version and
    clean up the default ``'0'`` layer settings.

    Returns
    -------
    ezdxf.document.Drawing
    """
    doc = ezdxf.new(dxfversion=DXF_VERSION)

    # Use metric units (millimetres = 4, metres = 6)
    doc.header["$INSUNITS"] = 6   # metres
    doc.header["$MEASUREMENT"] = 1  # metric

    return doc


def _add_layers(doc: Drawing) -> None:
    """
    Register the three survey layers in the DXF layer table.

    Uses ``LayerTable.has_entry()`` to check existence before adding —
    ``LayerTable.get()`` in ezdxf >= 1.3 raises ``DXFTableEntryError``
    when the layer is absent instead of returning ``None``.

    Parameters
    ----------
    doc:
        The target DXF document.
    """
    lt = doc.layers

    # Layer definitions: (name, ACI colour index)
    layer_defs: list[tuple[str, int]] = [
        (DXF_LAYER_BOUNDARY, DXF_COLOR_BOUNDARY),
        (DXF_LAYER_POINTS,   DXF_COLOR_POINTS),
        (DXF_LAYER_LABELS,   DXF_COLOR_LABELS),
    ]

    for name, color in layer_defs:
        if not lt.has_entry(name):
            lt.add(name=name, color=color, linetype="CONTINUOUS")
            logger.debug("Created DXF layer '%s' (color ACI %d).", name, color)


def _scaled_text_height(metrics: GeometryMetrics) -> float:
    """
    Derive a sensible text height relative to the bounding-box diagonal.

    A fixed DXF_TEXT_HEIGHT works for unit-scale drawings; for real-world
    survey coordinates (e.g. 500 m wide) we scale proportionally so labels
    remain legible without manual tweaking.

    Parameters
    ----------
    metrics:
        Pre-computed geometry metrics.

    Returns
    -------
    float
        Text height in coordinate units.
    """
    diagonal = (metrics.bbox_width ** 2 + metrics.bbox_height ** 2) ** 0.5
    if diagonal == 0.0:
        return DXF_TEXT_HEIGHT
    # Scale so text is roughly 1.5 % of the diagonal
    return max(DXF_TEXT_HEIGHT, diagonal * 0.015)


def _add_boundary(msp: ezdxf.layouts.Modelspace, polyline: Polyline) -> None:
    """
    Add the closed survey boundary as a single LWPolyline entity.

    Parameters
    ----------
    msp:
        Model-space layout of the target document.
    polyline:
        The survey boundary object.
    """
    coords_2d = [(e, n) for e, n in polyline.coordinates]

    lwpoly = msp.add_lwpolyline(
        points=coords_2d,
        dxfattribs={
            "layer": DXF_LAYER_BOUNDARY,
            "color": DXF_COLOR_BOUNDARY,
            "closed": True,          # ezdxf flag – explicitly closes the polyline
            "lineweight": 30,        # 0.30 mm, a standard survey line weight
        },
    )
    lwpoly.closed = True
    logger.debug("Added LWPolyline with %d vertices.", len(coords_2d))


def _add_points(msp: ezdxf.layouts.Modelspace, polyline: Polyline) -> None:
    """
    Add a POINT entity at each survey vertex.

    Parameters
    ----------
    msp:
        Model-space layout.
    polyline:
        The survey boundary object.
    """
    for pt in polyline.points:
        msp.add_point(
            location=(pt.easting, pt.northing, 0.0),
            dxfattribs={
                "layer": DXF_LAYER_POINTS,
                "color": DXF_COLOR_POINTS,
            },
        )
    logger.debug("Added %d POINT entities.", len(polyline.points))


def _add_labels(
    msp: ezdxf.layouts.Modelspace,
    polyline: Polyline,
    text_height: float,
) -> None:
    """
    Add a TEXT entity beside each survey point showing its Point_ID.

    Labels are offset slightly to the upper-right of the point so they
    do not overwrite the POINT marker.

    Parameters
    ----------
    msp:
        Model-space layout.
    polyline:
        The survey boundary object.
    text_height:
        Text height in coordinate units.
    """
    offset = text_height * 0.6  # small nudge away from the marker

    for pt in polyline.points:
        msp.add_text(
            text=pt.point_id,
            dxfattribs={
                "layer": DXF_LAYER_LABELS,
                "color": DXF_COLOR_LABELS,
                "height": text_height,
                "insert": (pt.easting + offset, pt.northing + offset),
            },
        )
    logger.debug("Added %d TEXT label entities.", len(polyline.points))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_dxf(
    polyline: Polyline,
    metrics: GeometryMetrics,
) -> Drawing:
    """
    Build a complete DXF :class:`~ezdxf.document.Drawing` from a survey boundary.

    Parameters
    ----------
    polyline:
        The closed survey boundary.
    metrics:
        Pre-computed geometry metrics used to scale text labels.

    Returns
    -------
    ezdxf.document.Drawing
        In-memory DXF document ready to be saved or streamed.
    """
    doc = _create_document()
    _add_layers(doc)

    msp = doc.modelspace()
    text_height = _scaled_text_height(metrics)

    _add_boundary(msp, polyline)
    _add_points(msp, polyline)
    _add_labels(msp, polyline, text_height)

    logger.info(
        "DXF document generated: %d points, text height=%.4f.",
        polyline.point_count,
        text_height,
    )
    return doc


def save_dxf(
    doc: Drawing,
    filename: str = DEFAULT_DXF_FILENAME,
    output_dir: str = OUTPUT_DIR,
) -> Path:
    """
    Save a DXF document to the ``outputs/`` directory on disk.

    Parameters
    ----------
    doc:
        DXF document returned by :func:`generate_dxf`.
    filename:
        Target filename (basename only, no path).
    output_dir:
        Directory to write into.  Created if it does not exist.

    Returns
    -------
    pathlib.Path
        Absolute path of the saved file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / filename
    doc.saveas(str(out_path))

    logger.info("DXF saved to: %s", out_path.resolve())
    return out_path.resolve()


def dxf_to_bytes(doc: Drawing) -> bytes:
    """
    Serialise a DXF document to a :class:`bytes` object.

    Used by the Streamlit UI to offer an in-browser download without
    writing a temporary file to disk.

    Parameters
    ----------
    doc:
        DXF document returned by :func:`generate_dxf`.

    Returns
    -------
    bytes
        Raw DXF file content.
    """
    buffer = io.StringIO()
    doc.write(buffer)
    return buffer.getvalue().encode("utf-8")
