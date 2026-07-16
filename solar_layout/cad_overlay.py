"""
solar_layout/cad_overlay.py
----------------------------
Adds the solar panel layout as new DXF layers on top of an existing
ezdxf Drawing produced by the existing cad/dxf_generator module.

Single responsibility: DXF layer creation and entity drawing only.
No geometry calculations, no panel placement, no UI.

The existing Drawing is NEVER mutated destructively — only new layers
and new entities are appended to the model-space.  All existing survey
layers (SURVEY_BOUNDARY, SURVEY_POINTS, SURVEY_LABELS) are untouched.

New layers added
----------------
SOLAR_PANELS          – one closed LWPolyline rectangle per panel (cyan)
SOLAR_USABLE_BOUNDARY – LWPolyline of the usable area after setback (magenta)
SOLAR_LABELS          – summary text block in the drawing (white/black)
SOLAR_DIMENSIONS      – optional dimension annotations (blue)
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment

from solar_layout.config import (
    DXF_COLOR_SOLAR_BOUNDARY,
    DXF_COLOR_SOLAR_DIMS,
    DXF_COLOR_SOLAR_LABELS,
    DXF_COLOR_SOLAR_PANELS,
    DXF_LAYER_SOLAR_BOUNDARY,
    DXF_LAYER_SOLAR_DIMS,
    DXF_LAYER_SOLAR_LABELS,
    DXF_LAYER_SOLAR_PANELS,
    DXF_PANEL_LINEWEIGHT,
    SOLAR_OUTPUT_SUFFIX,
)
from solar_layout.geometry_utils import polygon_exterior_coords
from solar_layout.layout_engine import SolarLayoutResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_solar_layers(doc: Drawing) -> None:
    """
    Register all solar overlay layers in the DXF layer table.

    Safe to call on a Drawing that already has some or all layers — uses
    ``has_entry`` to avoid duplicate-layer errors.

    Parameters
    ----------
    doc:
        The ezdxf Drawing to modify.
    """
    lt = doc.layers

    layer_defs: list[tuple[str, int]] = [
        (DXF_LAYER_SOLAR_PANELS,   DXF_COLOR_SOLAR_PANELS),
        (DXF_LAYER_SOLAR_BOUNDARY, DXF_COLOR_SOLAR_BOUNDARY),
        (DXF_LAYER_SOLAR_LABELS,   DXF_COLOR_SOLAR_LABELS),
        (DXF_LAYER_SOLAR_DIMS,     DXF_COLOR_SOLAR_DIMS),
    ]

    for name, color in layer_defs:
        if not lt.has_entry(name):
            lt.add(name=name, color=color, linetype="CONTINUOUS")
            logger.debug("Created DXF layer '%s' (ACI %d).", name, color)


def _add_panel_rectangles(
    msp,
    result: SolarLayoutResult,
) -> int:
    """
    Draw one closed LWPolyline per solar panel in the SOLAR_PANELS layer.

    Parameters
    ----------
    msp:
        ezdxf model-space layout.
    result:
        Completed SolarLayoutResult containing placement.panels.

    Returns
    -------
    int
        Number of panel entities added.
    """
    if result.placement is None or not result.placement.panels:
        return 0

    count = 0
    for panel_poly in result.placement.panels:
        # Extract the 4 corner coordinates of the rectangle
        coords = list(panel_poly.exterior.coords)
        # ezdxf expects 2-D points; drop the closing duplicate
        pts_2d = [(float(x), float(y)) for x, y in coords[:-1]]

        lwpoly = msp.add_lwpolyline(
            points=pts_2d,
            dxfattribs={
                "layer": DXF_LAYER_SOLAR_PANELS,
                "color": DXF_COLOR_SOLAR_PANELS,
                "lineweight": DXF_PANEL_LINEWEIGHT,
                "closed": True,
            },
        )
        lwpoly.closed = True
        count += 1

    logger.debug("Added %d panel rectangle(s) to DXF.", count)
    return count


def _add_usable_boundary(
    msp,
    result: SolarLayoutResult,
) -> None:
    """
    Draw the usable-area boundary (after setback) as a single LWPolyline
    in the SOLAR_USABLE_BOUNDARY layer.

    Parameters
    ----------
    msp:
        ezdxf model-space layout.
    result:
        SolarLayoutResult with a valid usable_area.usable_polygon.
    """
    if result.usable_area is None:
        return

    coords = polygon_exterior_coords(result.usable_area.usable_polygon)
    if len(coords) < 2:
        return

    pts_2d = [(float(x), float(y)) for x, y in coords]

    lwpoly = msp.add_lwpolyline(
        points=pts_2d,
        dxfattribs={
            "layer": DXF_LAYER_SOLAR_BOUNDARY,
            "color": DXF_COLOR_SOLAR_BOUNDARY,
            "lineweight": 18,   # 0.18 mm — lighter than the survey boundary
            "closed": True,
        },
    )
    lwpoly.closed = True
    logger.debug("Added usable-boundary LWPolyline (%d vertices).", len(pts_2d))


def _scaled_label_height(result: SolarLayoutResult) -> float:
    """
    Derive a text height for overlay labels proportional to the land area.

    Uses 1.5 % of the bounding-box diagonal, with a floor of 0.5 m.

    Parameters
    ----------
    result:
        SolarLayoutResult for bounding-box dimensions.

    Returns
    -------
    float
        Text height in coordinate units (metres).
    """
    if result.land_polygon is None:
        return 2.0

    minx, miny, maxx, maxy = result.land_polygon.bounds
    diagonal = ((maxx - minx) ** 2 + (maxy - miny) ** 2) ** 0.5
    return max(0.5, diagonal * 0.015)


def _add_summary_label(
    msp,
    result: SolarLayoutResult,
    text_height: float,
) -> None:
    """
    Insert a compact multi-line summary text block near the south-west
    corner of the land boundary, in the SOLAR_LABELS layer.

    Parameters
    ----------
    msp:
        ezdxf model-space layout.
    result:
        Completed SolarLayoutResult.
    text_height:
        Text height in coordinate units.
    """
    if result.land_polygon is None:
        return

    minx, miny, _, _ = result.land_polygon.bounds
    # Place the block just below and to the left of the SW corner
    origin_x = minx
    origin_y = miny - text_height * 8  # 8 lines of breathing room below

    from solar_layout.capacity_calculator import format_capacity, format_energy

    lines: list[str] = [
        "--- SOLAR LAYOUT SUMMARY ---",
        f"Panels         : {result.panel_count}",
        f"Orientation    : {result.orientation_used.capitalize()}",
        f"Total Area     : {result.total_area_m2:,.1f} m²",
        f"Usable Area    : {result.usable_area_m2:,.1f} m²",
        f"Panel Area     : {result.total_panel_area_m2:,.1f} m²",
        f"Remaining Area : {result.remaining_area_m2:,.1f} m²",
        f"Capacity       : {format_capacity(result.installed_capacity_kwp)}",
        f"Layout Eff.    : {result.layout_efficiency_pct:.1f} %",
        f"GCR            : {result.ground_coverage_ratio:.3f}",
    ]

    if result.capacity:
        lines.append(
            f"Annual Yield   : {format_energy(result.capacity.estimated_annual_yield_kwh)}"
        )

    for i, line in enumerate(lines):
        y_pos = origin_y - i * text_height * 1.5
        msp.add_text(
            text=line,
            dxfattribs={
                "layer": DXF_LAYER_SOLAR_LABELS,
                "color": DXF_COLOR_SOLAR_LABELS,
                "height": text_height,
                "insert": (origin_x, y_pos),
            },
        )

    logger.debug("Added %d summary label line(s) to DXF.", len(lines))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_solar_overlay(
    doc: Drawing,
    result: SolarLayoutResult,
) -> Drawing:
    """
    Add the solar layout overlay to an existing ezdxf Drawing.

    The Drawing is modified **in-place** (new layers and entities appended).
    Existing survey content is completely untouched.

    Parameters
    ----------
    doc:
        An ezdxf Drawing, typically the one already generated by
        ``cad.dxf_generator.generate_dxf``.
    result:
        Completed :class:`~solar_layout.layout_engine.SolarLayoutResult`.
        When ``result.panel_count == 0`` only the usable boundary and
        summary label are added (no panel rectangles).

    Returns
    -------
    ezdxf.document.Drawing
        The same Drawing object with the solar overlay appended.
    """
    _ensure_solar_layers(doc)
    msp = doc.modelspace()

    # 1. Usable boundary outline
    _add_usable_boundary(msp, result)

    # 2. Panel rectangles
    panels_added = _add_panel_rectangles(msp, result)

    # 3. Summary label block
    text_height = _scaled_label_height(result)
    _add_summary_label(msp, result, text_height)

    logger.info(
        "Solar overlay applied: %d panels drawn, usable boundary drawn, "
        "summary label added.",
        panels_added,
    )

    return doc


def save_solar_dxf(
    doc: Drawing,
    base_stem: str,
    output_dir: str = "outputs",
) -> Path:
    """
    Save the solar-overlay DXF to disk.

    The filename is derived by appending :data:`SOLAR_OUTPUT_SUFFIX` to
    *base_stem*, e.g. ``'coordinates_dataset_20260713_141835_solar_layout.dxf'``.

    Parameters
    ----------
    doc:
        The Drawing to save (already has solar overlay applied).
    base_stem:
        Stem of the original DXF filename (without extension).
    output_dir:
        Directory to write into.  Created if absent.

    Returns
    -------
    pathlib.Path
        Absolute path of the saved file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{base_stem}{SOLAR_OUTPUT_SUFFIX}.dxf"
    out_path = out_dir / filename
    doc.saveas(str(out_path))

    logger.info("Solar DXF saved: %s", out_path.resolve())
    return out_path.resolve()


def solar_dxf_to_bytes(doc: Drawing) -> bytes:
    """
    Serialise the solar-overlay Drawing to bytes for in-browser download.

    Parameters
    ----------
    doc:
        The Drawing with solar overlay applied.

    Returns
    -------
    bytes
        Raw DXF file content.
    """
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8", errors="replace")
