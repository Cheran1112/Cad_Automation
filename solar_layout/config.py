"""
solar_layout/config.py
----------------------
All tuneable constants for the Solar Layout Planning module.

This file is the single source of truth for panel dimensions, engineering
constraints, DXF styling, and output paths used by the solar module.

No other module should hard-code magic values — import from here instead.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Module feature flag
# ---------------------------------------------------------------------------
# Set to False to completely disable the solar layout section in the UI.
SOLAR_MODULE_ENABLED: bool = True

# ---------------------------------------------------------------------------
# Solar panel physical dimensions (metres)
# ---------------------------------------------------------------------------
# Standard utility-scale monocrystalline bifacial panel (e.g. 550 Wp)
PANEL_WIDTH_M: float = 1.134   # shorter dimension (portrait width / landscape height)
PANEL_HEIGHT_M: float = 2.278  # longer dimension  (portrait height / landscape width)
PANEL_POWER_WP: float = 550.0  # nameplate capacity in Watts-peak per panel

# ---------------------------------------------------------------------------
# Panel orientation modes
# ---------------------------------------------------------------------------
# 'portrait'   – width along X-axis, height along Y-axis
# 'landscape'  – height along X-axis, width along Y-axis
ORIENTATION_PORTRAIT: str = "portrait"
ORIENTATION_LANDSCAPE: str = "landscape"
DEFAULT_ORIENTATION: str = ORIENTATION_PORTRAIT

# Available orientations for UI selection
AVAILABLE_ORIENTATIONS: list[str] = [ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE]

# ---------------------------------------------------------------------------
# Engineering spacing constraints (metres)
# ---------------------------------------------------------------------------
# Setback from the land boundary polygon inward
BOUNDARY_SETBACK_M: float = 3.0

# Minimum gap between two panels in the same row (inter-panel gap)
INTER_PANEL_GAP_M: float = 0.02   # 20 mm structural tolerance

# Gap between the right edge of one column and the left edge of the next
# (maintenance aisle / cable route between columns)
INTER_COLUMN_GAP_M: float = 0.05  # 50 mm (panels are typically linked in portrait rows)

# Gap between rows (north-south spacing for shadow avoidance / maintenance)
INTER_ROW_SPACING_M: float = 3.5  # typical for ~15–25 ° tilt in tropical regions

# Width reserved along one edge of the usable area for a utility/road corridor
UTILITY_CORRIDOR_WIDTH_M: float = 0.0  # set > 0 to carve out a reserved strip

# ---------------------------------------------------------------------------
# Default panel array: number of panels per string in a row
# ---------------------------------------------------------------------------
# How many panels are placed side-by-side in the east-west direction before
# a column gap is inserted.  Set to 0 to treat the entire row as one string.
PANELS_PER_STRING: int = 0  # 0 = no string-level column grouping (free packing)

# ---------------------------------------------------------------------------
# Capacity and performance
# ---------------------------------------------------------------------------
# DC-to-AC inverter efficiency (fraction, 0–1)
INVERTER_EFFICIENCY: float = 0.98

# DC cable / mismatch losses (fraction of nameplate)
DC_LOSSES: float = 0.02

# Combined performance ratio used for energy yield estimates
PERFORMANCE_RATIO: float = 0.80

# Peak sun hours per day (location-dependent; used for rough daily yield)
PEAK_SUN_HOURS: float = 5.5  # reasonable default for Indian subcontinent

# ---------------------------------------------------------------------------
# DXF layer / style for the solar overlay
# ---------------------------------------------------------------------------
DXF_LAYER_SOLAR_PANELS: str = "SOLAR_PANELS"
DXF_LAYER_SOLAR_BOUNDARY: str = "SOLAR_USABLE_BOUNDARY"
DXF_LAYER_SOLAR_LABELS: str = "SOLAR_LABELS"
DXF_LAYER_SOLAR_DIMS: str = "SOLAR_DIMENSIONS"

# ACI colour indices
DXF_COLOR_SOLAR_PANELS: int = 4      # Cyan
DXF_COLOR_SOLAR_BOUNDARY: int = 6    # Magenta
DXF_COLOR_SOLAR_LABELS: int = 7      # White / Black (paper-dependent)
DXF_COLOR_SOLAR_DIMS: int = 5        # Blue

# Line weight for panel outlines (in hundredths of mm: 13 = 0.13 mm)
DXF_PANEL_LINEWEIGHT: int = 13

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
SOLAR_OUTPUT_SUFFIX: str = "_solar_layout"   # appended to the base DXF stem
SOLAR_REPORT_SUFFIX: str = "_solar_report"   # appended to the base stem for JSON

# ---------------------------------------------------------------------------
# Geometry precision
# ---------------------------------------------------------------------------
# Shapely buffer resolution (number of segments used to approximate curved edges)
BUFFER_RESOLUTION: int = 16

# Minimum usable area (m²) below which layout is skipped with a warning
MIN_USABLE_AREA_M2: float = 10.0

# Tolerance used for floating-point boundary comparisons (metres)
GEOMETRY_TOLERANCE_M: float = 1e-4
