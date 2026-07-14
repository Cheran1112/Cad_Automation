"""
app.py
------
Streamlit entry point for the CAD Automation Platform – Version 1.

This module is the ONLY place where Streamlit is imported.
All business logic (reading, validation, geometry, DXF, preview, location)
lives in dedicated packages; app.py only orchestrates them and handles UI
state.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import sys
import os

# ---------------------------------------------------------------------------
# Make all sub-packages importable when running from the cad_automation/ dir
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

import logging
import matplotlib
matplotlib.use("Agg")  # non-interactive backend – must be set before pyplot import

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from cad.dxf_generator import dxf_to_bytes, generate_dxf, save_dxf
from config import (
    APP_NAME,
    APP_VERSION,
    COL_EASTING,
    COL_NORTHING,
    COL_POINT_ID,
    DEFAULT_CRS,
    DEFAULT_DXF_FILENAME,
    OUTPUT_DIR,
    SUPPORTED_CRS,
)
from data.reader import FileReadError, UnsupportedFileTypeError, read_file
from geometry.calculator import GeometryMetrics, compute_metrics
from geometry.polyline import Polyline
from location.coordinate_converter import detect_coordinate_format
from location.location_service import LocationResult, detect_location
from preview.plotter import build_preview_figure
from reports.location_report import build_location_report
from utils.helpers import (
    build_metrics_table,
    format_area,
    format_coordinate,
    format_distance,
    safe_stem,
    timestamped_filename,
)
from utils.logger import configure_logging, get_logger
from validation.validator import ValidationResult, validate

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
configure_logging(level=logging.INFO)
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Page configuration – must be the first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=APP_NAME,
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Session-state keys
# ---------------------------------------------------------------------------
_KEY_DF            = "dataframe"
_KEY_VALIDATION    = "validation_result"
_KEY_POLYLINE      = "polyline"
_KEY_METRICS       = "metrics"
_KEY_DXF_BYTES     = "dxf_bytes"
_KEY_DXF_FILENAME  = "dxf_filename"
_KEY_UPLOADED_NAME = "uploaded_name"
# Location detection
_KEY_LOCATION_RESULT = "location_result"
_KEY_SELECTED_CRS    = "selected_crs"
_KEY_COORD_FORMAT    = "coord_format"
# Import-time coordinate detection metadata
_KEY_IMPORT_FORMAT   = "import_coord_format"   # 'easting_northing' | 'latitude_longitude'
_KEY_IMPORT_SRC_CRS  = "import_source_crs"     # 'native' | 'EPSG:4326'
_KEY_IMPORT_TGT_EPSG = "import_target_epsg"    # '' | 'EPSG:32644' etc.


def _init_state() -> None:
    """Initialise all session-state keys to None on first load."""
    for key in (
        _KEY_DF,
        _KEY_VALIDATION,
        _KEY_POLYLINE,
        _KEY_METRICS,
        _KEY_DXF_BYTES,
        _KEY_DXF_FILENAME,
        _KEY_UPLOADED_NAME,
        _KEY_LOCATION_RESULT,
        _KEY_SELECTED_CRS,
        _KEY_COORD_FORMAT,
        _KEY_IMPORT_FORMAT,
        _KEY_IMPORT_SRC_CRS,
        _KEY_IMPORT_TGT_EPSG,
    ):
        if key not in st.session_state:
            st.session_state[key] = None


# ---------------------------------------------------------------------------
# UI section renderers
# ---------------------------------------------------------------------------

def _render_sidebar() -> None:
    """Render the left sidebar with branding and workflow guide."""
    with st.sidebar:
        st.markdown(f"## 📐 {APP_NAME}")
        st.caption(f"Version {APP_VERSION}")
        st.divider()

        st.markdown("### Workflow")
        st.markdown(
            """
1. **Upload** an Excel or CSV file
2. **Review** the data preview
3. **Check** validation results
4. **Inspect** the geometry preview
5. **Generate** the DXF boundary
6. **Download** the DXF file
7. **Detect** the survey location
"""
        )
        st.divider()

        st.markdown("### Required Columns")
        st.code("Point_ID\nEasting\nNorthing", language="text")
        st.caption(
            "Column names are case-insensitive. "
            "Aliases accepted: Point, Pt, Point No, X/Y."
        )

        st.divider()
        st.markdown("### Supported Formats")
        st.markdown("- Excel `.xlsx`\n- CSV `.csv`")


def _render_upload_section() -> None:
    """
    Section 1 – File upload.
    Reads the file, stores the DataFrame in session state.
    Resets all downstream state when a new file is uploaded.
    """
    st.header("1 · Upload Survey File")

    uploaded = st.file_uploader(
        label="Choose an Excel (.xlsx) or CSV (.csv) file",
        type=["xlsx", "csv"],
        help="The file must contain Point_ID, Easting, and Northing columns.",
    )

    if uploaded is None:
        st.info("Upload a survey file to begin.", icon="📂")
        return

    # Only re-process when the uploaded file actually changes
    if st.session_state[_KEY_UPLOADED_NAME] != uploaded.name:
        # Reset ALL downstream state including location
        for key in (
            _KEY_DF,
            _KEY_VALIDATION,
            _KEY_POLYLINE,
            _KEY_METRICS,
            _KEY_DXF_BYTES,
            _KEY_DXF_FILENAME,
            _KEY_LOCATION_RESULT,
            _KEY_SELECTED_CRS,
            _KEY_COORD_FORMAT,
        ):
            st.session_state[key] = None

        st.session_state[_KEY_UPLOADED_NAME] = uploaded.name

        with st.spinner("Reading file…"):
            try:
                # read_file() now returns a ReadResult named-tuple.
                # Extract the DataFrame immediately so _KEY_DF always holds
                # a plain pd.DataFrame — every downstream section is unchanged.
                result = read_file(uploaded, filename=uploaded.name)
                st.session_state[_KEY_DF]             = result.df
                st.session_state[_KEY_IMPORT_FORMAT]   = result.coord_format
                st.session_state[_KEY_IMPORT_SRC_CRS]  = result.source_crs
                st.session_state[_KEY_IMPORT_TGT_EPSG] = result.target_epsg
                logger.info(
                    "Loaded '%s' – %d rows, format=%s.",
                    uploaded.name, len(result.df), result.coord_format,
                )
            except UnsupportedFileTypeError as exc:
                st.error(f"Unsupported file type: {exc}", icon="🚫")
                return
            except (FileReadError, KeyError) as exc:
                st.error(f"Failed to read file: {exc}", icon="❌")
                return

    if st.session_state[_KEY_DF] is not None:
        df: pd.DataFrame = st.session_state[_KEY_DF]
        st.success(
            f"File loaded: **{uploaded.name}** — {len(df)} point(s) found.",
            icon="✅",
        )


def _render_data_preview() -> None:
    """Section 2 – Interactive data table."""
    df: pd.DataFrame | None = st.session_state[_KEY_DF]
    if df is None:
        return

    st.header("2 · Data Preview")

    col_left, col_right = st.columns([3, 1])

    with col_left:
        st.dataframe(
            df.style.format(
                {
                    COL_EASTING: "{:,.3f}",
                    COL_NORTHING: "{:,.3f}",
                }
            ),
            use_container_width=True,
            height=min(400, 35 * (len(df) + 1)),
        )

    with col_right:
        st.markdown("**Summary**")
        st.metric("Total Points", len(df))
        st.metric(
            "Easting Range",
            f"{format_coordinate(float(df[COL_EASTING].min()))} –\n"
            f"{format_coordinate(float(df[COL_EASTING].max()))}",
        )
        st.metric(
            "Northing Range",
            f"{format_coordinate(float(df[COL_NORTHING].min()))} –\n"
            f"{format_coordinate(float(df[COL_NORTHING].max()))}",
        )


def _render_validation_section() -> None:
    """
    Section 3 – Validation.
    Auto-validates on first load; re-validate button clears cached result.
    """
    df: pd.DataFrame | None = st.session_state[_KEY_DF]
    if df is None:
        return

    st.header("3 · Validation")

    # Auto-validate on first load of a new file
    if st.session_state[_KEY_VALIDATION] is None:
        with st.spinner("Validating data…"):
            result: ValidationResult = validate(df)
            st.session_state[_KEY_VALIDATION] = result
            logger.info("Validation: %s", result.summary())
    else:
        result = st.session_state[_KEY_VALIDATION]

    # Display summary badge
    if result.is_valid:
        label = (
            f"Validation passed — {result.warning_count} warning(s)."
            if result.warnings
            else "Validation passed — no issues found."
        )
        st.success(label, icon="✅")
    else:
        st.error(
            f"Validation failed — {result.error_count} error(s), "
            f"{result.warning_count} warning(s). "
            "Fix the issues below before generating the DXF.",
            icon="❌",
        )

    # Detailed issue list
    if result.issues:
        with st.expander("View validation details", expanded=not result.is_valid):
            for issue in result.issues:
                icon = "🔴" if issue.severity == "error" else "🟡"
                row_info = f"  *(rows: {issue.rows})*" if issue.rows else ""
                st.markdown(
                    f"{icon} **[{issue.code}]** {issue.message}{row_info}"
                )

    # Allow re-validation after manual edits (future: inline editing)
    if st.button("Re-validate", key="btn_revalidate"):
        st.session_state[_KEY_VALIDATION] = None
        st.session_state[_KEY_POLYLINE] = None
        st.session_state[_KEY_METRICS] = None
        st.session_state[_KEY_DXF_BYTES] = None
        st.rerun()


def _build_geometry() -> bool:
    """
    Build the Polyline and GeometryMetrics from the validated DataFrame.

    Returns True if geometry is ready, False on any failure.
    """
    if st.session_state[_KEY_POLYLINE] is not None:
        return True  # already built

    df: pd.DataFrame = st.session_state[_KEY_DF]
    try:
        polyline = Polyline.from_dataframe(df)
        metrics = compute_metrics(polyline)
        st.session_state[_KEY_POLYLINE] = polyline
        st.session_state[_KEY_METRICS] = metrics
        logger.info(
            "Geometry built: %d points, area=%.4f, perimeter=%.4f.",
            polyline.point_count,
            metrics.area_abs,
            metrics.perimeter,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        st.error(f"Geometry engine error: {exc}", icon="⚠️")
        logger.exception("Geometry build failed.")
        return False


def _render_geometry_preview() -> None:
    """
    Section 4 – Geometry Preview.
    Only rendered when validation has passed.
    """
    result: ValidationResult | None = st.session_state[_KEY_VALIDATION]
    if result is None or not result.is_valid:
        return

    st.header("4 · Geometry Preview")

    if not _build_geometry():
        return

    polyline: Polyline = st.session_state[_KEY_POLYLINE]
    metrics: GeometryMetrics = st.session_state[_KEY_METRICS]

    # ── Metrics cards ──────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Points", polyline.point_count)
    col2.metric("Area", format_area(metrics.area_abs))
    col3.metric("Perimeter", format_distance(metrics.perimeter))
    col4.metric(
        "Centroid",
        f"E {format_coordinate(metrics.centroid_easting, decimals=2)}\n"
        f"N {format_coordinate(metrics.centroid_northing, decimals=2)}",
    )

    st.divider()

    # ── Segment table (collapsible) ────────────────────────────────────────
    with st.expander("Segment details", expanded=False):
        seg_data = []
        for seg in polyline.segments:
            seg_data.append(
                {
                    "From": seg.start.point_id,
                    "To": seg.end.point_id,
                    "Length (m)": f"{seg.length:,.4f}",
                    "Bearing (°)": f"{seg.bearing_degrees:.4f}",
                }
            )
        st.dataframe(pd.DataFrame(seg_data), use_container_width=True)

    # ── Matplotlib figure ─────────────────────────────────────────────────
    with st.spinner("Rendering preview…"):
        fig = build_preview_figure(polyline, metrics)
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)  # release memory


def _render_dxf_section() -> None:
    """
    Section 5 – DXF generation and download.
    Only rendered when geometry is available.
    """
    polyline: Polyline | None = st.session_state[_KEY_POLYLINE]
    metrics: GeometryMetrics | None = st.session_state[_KEY_METRICS]

    if polyline is None or metrics is None:
        return

    st.header("5 · Generate & Download DXF")

    col_gen, col_dl = st.columns([1, 2])

    with col_gen:
        if st.button("Generate DXF", type="primary", key="btn_generate_dxf"):
            with st.spinner("Generating DXF…"):
                try:
                    uploaded_name: str = st.session_state[_KEY_UPLOADED_NAME] or "survey"
                    stem = safe_stem(uploaded_name)
                    filename = timestamped_filename(stem, "dxf")

                    doc = generate_dxf(polyline, metrics)
                    dxf_bytes = dxf_to_bytes(doc)

                    # Also persist to disk
                    save_dxf(doc, filename=filename, output_dir=OUTPUT_DIR)

                    st.session_state[_KEY_DXF_BYTES] = dxf_bytes
                    st.session_state[_KEY_DXF_FILENAME] = filename

                    logger.info("DXF generated: %s (%d bytes).", filename, len(dxf_bytes))
                    st.success(f"DXF ready: **{filename}**", icon="✅")

                except Exception as exc:  # noqa: BLE001
                    st.error(f"DXF generation failed: {exc}", icon="❌")
                    logger.exception("DXF generation error.")

    with col_dl:
        dxf_bytes: bytes | None = st.session_state[_KEY_DXF_BYTES]
        dxf_filename: str | None = st.session_state[_KEY_DXF_FILENAME]

        if dxf_bytes is not None and dxf_filename is not None:
            st.download_button(
                label="⬇  Download DXF",
                data=dxf_bytes,
                file_name=dxf_filename,
                mime="application/dxf",
                key="btn_download_dxf",
                type="secondary",
            )

            # DXF layer info
            with st.expander("DXF layer information", expanded=False):
                layer_info = [
                    {
                        "Layer": "SURVEY_BOUNDARY",
                        "Content": "Closed LWPolyline – the survey boundary",
                        "Colour (ACI)": "2 – Yellow",
                        "Line weight": "0.30 mm",
                    },
                    {
                        "Layer": "SURVEY_POINTS",
                        "Content": "POINT entities at each vertex",
                        "Colour (ACI)": "1 – Red",
                        "Line weight": "default",
                    },
                    {
                        "Layer": "SURVEY_LABELS",
                        "Content": "TEXT labels (Point_ID)",
                        "Colour (ACI)": "3 – Green",
                        "Line weight": "default",
                    },
                ]
                st.dataframe(pd.DataFrame(layer_info), use_container_width=True)
        else:
            st.info("Click **Generate DXF** to create the file.", icon="💡")


def _render_location_section() -> None:
    """
    Section 6 – Automatic Location Detection.

    Supports two coordinate formats:
    - Lat/Lon files: geocode immediately, no CRS selection needed.
    - Easting/Northing files: show CRS dropdown, convert then geocode.

    This section is purely additive — the DXF workflow above is untouched.
    """
    df: pd.DataFrame | None = st.session_state[_KEY_DF]
    result_val: ValidationResult | None = st.session_state[_KEY_VALIDATION]

    # Only show after a valid file is loaded
    if df is None or result_val is None or not result_val.is_valid:
        return

    st.header("6 · Survey Location")

    # ── Detect coordinate format once per file ────────────────────────────
    if st.session_state[_KEY_COORD_FORMAT] is None:
        fmt = detect_coordinate_format(df)
        st.session_state[_KEY_COORD_FORMAT] = fmt

    coord_format: str = st.session_state[_KEY_COORD_FORMAT]

    # ── CRS dropdown (only for projected Easting/Northing files) ─────────
    selected_crs: str | None = None

    if coord_format == "projected":
        st.info(
            "This file uses **Easting / Northing** (projected) coordinates. "
            "Select the Coordinate Reference System (CRS) to enable "
            "location detection.",
            icon="🗺",
        )

        crs_labels = [label for label, _    in SUPPORTED_CRS]
        crs_codes  = [code  for _,     code in SUPPORTED_CRS]

        default_idx = (
            crs_codes.index(DEFAULT_CRS) if DEFAULT_CRS in crs_codes else 0
        )

        chosen_label: str = st.selectbox(
            label="Coordinate Reference System (CRS)",
            options=crs_labels,
            index=default_idx,
            key="crs_selectbox",
            help=(
                "Choose the CRS used when the survey was recorded. "
                "For India, EPSG:32643–32646 are UTM zones. "
                "EPSG:4326 is plain Latitude/Longitude (WGS84)."
            ),
        )
        selected_crs = crs_codes[crs_labels.index(chosen_label)]

        # Reset cached result whenever the CRS selection changes
        if st.session_state[_KEY_SELECTED_CRS] != selected_crs:
            st.session_state[_KEY_SELECTED_CRS] = selected_crs
            st.session_state[_KEY_LOCATION_RESULT] = None

    else:
        st.info(
            "This file contains **Latitude / Longitude** coordinates. "
            "Location detection will use them directly.",
            icon="📍",
        )

    # ── Detect button (forces a fresh run) ───────────────────────────────
    if st.button("Detect Location", type="primary", key="btn_detect_location"):
        st.session_state[_KEY_LOCATION_RESULT] = None

    # ── Run detection (cached per file + CRS combination) ────────────────
    if st.session_state[_KEY_LOCATION_RESULT] is None:
        with st.spinner("Detecting location…"):
            location_result: LocationResult = detect_location(
                df, source_crs=selected_crs
            )
            st.session_state[_KEY_LOCATION_RESULT] = location_result
            logger.info(
                "Location detection complete: succeeded=%s, format=%s.",
                location_result.succeeded,
                coord_format,
            )

    location_result: LocationResult = st.session_state[_KEY_LOCATION_RESULT]
    if location_result is None:
        return

    # ── Fatal error banner ────────────────────────────────────────────────
    if not location_result.succeeded:
        st.error(location_result.error, icon="❌")
        return

    # ── Non-fatal warnings (e.g. geocoding unavailable) ───────────────────
    for warning in location_result.warnings:
        st.warning(warning, icon="⚠️")

    # ── Build display-ready report ────────────────────────────────────────
    report = build_location_report(location_result)

    st.caption(f"📡 {report.coordinate_source}")
    st.divider()

    # ── Coordinate metric cards ───────────────────────────────────────────
    col_lat, col_lon, col_maps = st.columns([1, 1, 2])
    col_lat.metric("Latitude",  report.latitude)
    col_lon.metric("Longitude", report.longitude)

    with col_maps:
        if report.google_maps_url:
            st.link_button(
                label="🗺  Open in Google Maps",
                url=report.google_maps_url,
                use_container_width=True,
            )

    st.divider()

    # ── Geocoding detail cards ────────────────────────────────────────────
    if report.has_geocoding:
        # rows[0] = Latitude, rows[1] = Longitude — already shown above
        geo_rows = report.rows[2:]
        cols = st.columns(4)
        for idx, row in enumerate(geo_rows):
            label = f"{row.icon} {row.label}" if row.icon else row.label
            cols[idx % 4].metric(label=label, value=row.value)
    else:
        st.info(
            "Reverse geocoding could not retrieve place information. "
            "Coordinates are still available above.",
            icon="ℹ️",
        )

    # ── Full address string ───────────────────────────────────────────────
    if location_result.geocoding and location_result.geocoding.display_name:
        with st.expander("Full address", expanded=False):
            st.write(location_result.geocoding.display_name)

    # ── Location report table ─────────────────────────────────────────────
    with st.expander("Location report table", expanded=False):
        table_data = [{"Field": r.label, "Value": r.value} for r in report.rows]
        st.dataframe(
            pd.DataFrame(table_data),
            use_container_width=True,
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Application entry point."""
    _init_state()
    _render_sidebar()

    # Page title
    st.title(f"📐 {APP_NAME}")
    st.caption(
        "Upload a survey coordinate file to validate, preview, "
        "and export a professional CAD boundary drawing."
    )
    st.divider()

    # Sequential sections – each section only renders when its prerequisite
    # (previous section's output) is available in session state.
    _render_upload_section()
    _render_data_preview()
    _render_validation_section()
    _render_geometry_preview()
    _render_dxf_section()
    _render_location_section()


if __name__ == "__main__":
    main()
