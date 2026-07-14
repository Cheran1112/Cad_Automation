"""
config.py
---------
Central configuration for the CAD Automation Platform.
All tuneable constants live here so no other module hard-codes magic values.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Application metadata
# ---------------------------------------------------------------------------
APP_NAME: str = "CAD Automation Platform"
APP_VERSION: str = "1.0.0"

# ---------------------------------------------------------------------------
# Data ingestion
# ---------------------------------------------------------------------------
# Expected column names (case-insensitive matching is done in the reader)
COL_POINT_ID: str = "Point_ID"
COL_EASTING: str = "Easting"
COL_NORTHING: str = "Northing"

REQUIRED_COLUMNS: list[str] = [COL_POINT_ID, COL_EASTING, COL_NORTHING]

# ---------------------------------------------------------------------------
# Column alias mapping
# ---------------------------------------------------------------------------
# Maps every known survey-software variant to the canonical column name.
# Keys are the raw header strings exactly as they appear in the file
# (matching is applied case-insensitively in the reader).
# Add new aliases here as new export formats are encountered.
COLUMN_ALIASES: dict[str, str] = {
    # Point_ID variants
    "Point_ID":  COL_POINT_ID,
    "Point ID":  COL_POINT_ID,
    "Point":     COL_POINT_ID,
    "Point_No":  COL_POINT_ID,
    "Point No":  COL_POINT_ID,
    "Pt":        COL_POINT_ID,
    "Pt_ID":     COL_POINT_ID,
    "PtID":      COL_POINT_ID,
    "Name":      COL_POINT_ID,
    # Easting variants
    "Easting":   COL_EASTING,
    "East":      COL_EASTING,
    "E":         COL_EASTING,
    "X":         COL_EASTING,
    # Northing variants
    "Northing":  COL_NORTHING,
    "North":     COL_NORTHING,
    "N":         COL_NORTHING,
    "Y":         COL_NORTHING,
}

# ---------------------------------------------------------------------------
# Validation thresholds
# ---------------------------------------------------------------------------
MIN_POINTS: int = 3          # Minimum number of points to form a polygon
COORD_TOLERANCE: float = 1e-6  # Distance below which two points are considered identical

# ---------------------------------------------------------------------------
# DXF output settings
# ---------------------------------------------------------------------------
DXF_VERSION: str = "R2010"          # AutoCAD 2010 format – wide compatibility

DXF_LAYER_BOUNDARY: str = "SURVEY_BOUNDARY"
DXF_LAYER_POINTS: str = "SURVEY_POINTS"
DXF_LAYER_LABELS: str = "SURVEY_LABELS"

DXF_COLOR_BOUNDARY: int = 2   # Yellow  (ACI index)
DXF_COLOR_POINTS: int = 1     # Red
DXF_COLOR_LABELS: int = 3     # Green

DXF_TEXT_HEIGHT: float = 0.5  # Default text height; scaled later relative to bbox

# ---------------------------------------------------------------------------
# Preview / Matplotlib settings
# ---------------------------------------------------------------------------
PREVIEW_FIG_SIZE: tuple[float, float] = (10.0, 8.0)
PREVIEW_DPI: int = 100
PREVIEW_POINT_COLOR: str = "#E74C3C"   # red
PREVIEW_LINE_COLOR: str = "#2E86C1"    # blue
PREVIEW_LABEL_COLOR: str = "#1E8449"   # green
PREVIEW_LABEL_FONTSIZE: int = 8
PREVIEW_POINT_SIZE: int = 6

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
OUTPUT_DIR: str = "outputs"
DEFAULT_DXF_FILENAME: str = "survey_boundary.dxf"

# ---------------------------------------------------------------------------
# Location detection – coordinate formats
# ---------------------------------------------------------------------------
# Column names that indicate a file already carries geographic coordinates.
# Matching is applied case-insensitively in the reader/location service.
COL_LATITUDE: str = "Latitude"
COL_LONGITUDE: str = "Longitude"

# Aliases for latitude/longitude headers from various survey exporters
LATLON_ALIASES: dict[str, str] = {
    # Latitude variants
    "Latitude":  COL_LATITUDE,
    "Lat":       COL_LATITUDE,
    "LAT":       COL_LATITUDE,
    "lat":       COL_LATITUDE,
    # Longitude variants
    "Longitude": COL_LONGITUDE,
    "Lon":       COL_LONGITUDE,
    "Long":      COL_LONGITUDE,
    "LON":       COL_LONGITUDE,
    "lng":       COL_LONGITUDE,
    "Lng":       COL_LONGITUDE,
}

# ---------------------------------------------------------------------------
# Location detection – CRS / projection settings
# ---------------------------------------------------------------------------
# Each entry: (display label shown in UI, EPSG authority string for pyproj)
SUPPORTED_CRS: list[tuple[str, str]] = [
    ("EPSG:32643 – WGS 84 / UTM zone 43N (India West)",  "EPSG:32643"),
    ("EPSG:32644 – WGS 84 / UTM zone 44N (India Central)", "EPSG:32644"),
    ("EPSG:32645 – WGS 84 / UTM zone 45N (India East)",  "EPSG:32645"),
    ("EPSG:32646 – WGS 84 / UTM zone 46N",               "EPSG:32646"),
    ("EPSG:4326  – WGS 84 Geographic (Lat/Lon)",         "EPSG:4326"),
    ("EPSG:3857  – Web Mercator",                         "EPSG:3857"),
    ("EPSG:7755  – WGS 84 / India NSF LCC",              "EPSG:7755"),
    ("EPSG:24378 – Kalyanpur 1975 / India zone I",       "EPSG:24378"),
    ("EPSG:24379 – Kalyanpur 1975 / India zone IIa",     "EPSG:24379"),
    ("EPSG:24380 – Kalyanpur 1975 / India zone IIb",     "EPSG:24380"),
]

# Default CRS shown pre-selected in the UI dropdown
DEFAULT_CRS: str = "EPSG:32644"

# Target geographic CRS for all conversions (WGS84 lat/lon)
TARGET_CRS: str = "EPSG:4326"

# ---------------------------------------------------------------------------
# Location detection – geocoder settings
# ---------------------------------------------------------------------------
# Nominatim user-agent string (must be unique per application)
GEOCODER_USER_AGENT: str = "cad_automation_platform_v1"

# Maximum seconds to wait for a geocoder response
GEOCODER_TIMEOUT: int = 10

# Language for place names returned by Nominatim
GEOCODER_LANGUAGE: str = "en"

# Valid latitude / longitude bounds for sanity checking
LATITUDE_MIN: float = -90.0
LATITUDE_MAX: float = 90.0
LONGITUDE_MIN: float = -180.0
LONGITUDE_MAX: float = 180.0

# Google Maps base URL template
GOOGLE_MAPS_URL_TEMPLATE: str = "https://www.google.com/maps?q={lat},{lon}"