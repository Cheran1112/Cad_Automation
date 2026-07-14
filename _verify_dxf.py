"""
End-to-end smoke test: build a Polyline from sample data,
run generate_dxf(), and confirm the DXF contains all three layers.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
from geometry.polyline import Polyline
from geometry.calculator import compute_metrics
from cad.dxf_generator import generate_dxf, dxf_to_bytes
from config import DXF_LAYER_BOUNDARY, DXF_LAYER_POINTS, DXF_LAYER_LABELS

# Minimal valid survey dataset (4 points -> closed polygon)
data = {
    "Point_ID": ["B01", "B02", "B03", "B04"],
    "Easting":  [518980.691, 518964.561, 518950.123, 518960.789],
    "Northing": [2350645.822, 2350654.358, 2350630.100, 2350610.456],
}
df = pd.DataFrame(data)

polyline = Polyline.from_dataframe(df)
metrics  = compute_metrics(polyline)

print(f"Polyline: {polyline.point_count} points, area={metrics.area_abs:.2f}")

doc = generate_dxf(polyline, metrics)

# Confirm all three layers exist
for layer_name in (DXF_LAYER_BOUNDARY, DXF_LAYER_POINTS, DXF_LAYER_LABELS):
    assert doc.layers.has_entry(layer_name), f"MISSING LAYER: {layer_name}"
    print(f"  Layer present: {layer_name}")

# Confirm serialisation works
raw = dxf_to_bytes(doc)
assert len(raw) > 0, "dxf_to_bytes() returned empty bytes"
print(f"  DXF serialised: {len(raw):,} bytes")

print("\nAll checks passed.")
