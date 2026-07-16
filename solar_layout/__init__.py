"""
solar_layout
------------
Independent Solar Layout Planning module for the CAD Automation Platform.

This package is completely self-contained and attaches **after** the
existing CAD workflow.  Importing it has no side effects on any existing
module.

Public surface
--------------
The minimal public API needed by ``app.py`` is re-exported here so the
Streamlit layer only needs a single import line:

    from solar_layout import (
        SpacingRules,
        SolarLayoutResult,
        SolarReport,
        run_solar_layout,
        build_solar_report,
        solar_report_to_json,
        apply_solar_overlay,
        save_solar_dxf,
        solar_dxf_to_bytes,
        SOLAR_MODULE_ENABLED,
    )
"""

from solar_layout.cad_overlay import (
    apply_solar_overlay,
    save_solar_dxf,
    solar_dxf_to_bytes,
)
from solar_layout.config import SOLAR_MODULE_ENABLED
from solar_layout.layout_engine import SolarLayoutResult, run_solar_layout
from solar_layout.report_generator import (
    SolarReport,
    build_solar_report,
    solar_report_to_json,
)
from solar_layout.spacing_rules import SpacingRules

__all__ = [
    # Feature flag
    "SOLAR_MODULE_ENABLED",
    # Core pipeline
    "SpacingRules",
    "SolarLayoutResult",
    "run_solar_layout",
    # Report
    "SolarReport",
    "build_solar_report",
    "solar_report_to_json",
    # CAD overlay
    "apply_solar_overlay",
    "save_solar_dxf",
    "solar_dxf_to_bytes",
]
