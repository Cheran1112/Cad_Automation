"""
Diagnose the swapped-axis bug.

COLUMN_ALIASES contains:
    "N": COL_NORTHING   (i.e.  "n" → "Northing")
    "E": COL_EASTING    (i.e.  "e" → "Easting")

_detect_columns() checks:
    has_easting  = cols_lower & {"easting", "east", "e", "x"}
    has_northing = cols_lower & {"northing", "north", "n", "y"}

A Lat/Lon file with columns  ["Point", "Latitude", "Longitude"]  produces:
    cols_lower = {"point", "latitude", "longitude"}
    has_easting  → "e" in cols_lower?  NO
    has_northing → "n" in cols_lower?  NO
    has_lat      → "latitude" in latlon lower-keys?  YES
    has_lon      → "longitude" in latlon lower-keys?  YES
  → correctly detected as "latitude_longitude"   ✓

BUT what if the user's file has column names that happen to contain
single letters from COLUMN_ALIASES?  That is not the bug here.

The real issue: look at the transformer call order vs assignment:

    eastings, northings = transformer.transform(
        clean[COL_LONGITUDE].tolist(),   ← x (longitude) first  ✓
        clean[COL_LATITUDE].tolist(),    ← y (latitude)  second ✓
    )

With always_xy=True this is correct. But let's check whether
pyproj.Transformer.transform() with always_xy=True returns
(easting, northing) or (northing, easting).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from pyproj import Transformer
import pandas as pd
from shapely.geometry import LinearRing
from shapely.validation import explain_validity

# ── Verify axis order from pyproj ─────────────────────────────────────────
t = Transformer.from_crs("EPSG:4326", "EPSG:32644", always_xy=True)

# A single known point:  lat=13.082701, lon=80.275721  (Chennai)
# Expected UTM 44N:  E ≈ 421 000 range,  N ≈ 1 446 000 range
result = t.transform(80.275721, 13.082701)   # (lon, lat) → (easting, northing)
print(f"transform(lon, lat) → {result}")
print(f"  result[0] = {result[0]:.3f}  (expect ~421 000 = Easting)")
print(f"  result[1] = {result[1]:.3f}  (expect ~1 446 000 = Northing)")

# ── Now reproduce the polygon from the actual problem survey ────────────
# The bug: test with a boundary that was working with E/N but not with Lat/Lon.
# Typical survey boundary traversal order matters for non-convex shapes.
# The validator checks self-intersection, so if conversion SWAPS Lat/Lon
# the resulting polygon will very likely self-intersect.

# Simulate a file where columns are in the order: Point, Longitude, Latitude
# (i.e., Longitude BEFORE Latitude — which is a common export order)
from config import COL_POINT_ID, COL_EASTING, COL_NORTHING, COL_LATITUDE, COL_LONGITUDE

# Simulate _normalise_latlon_columns receiving a file where
# columns happen to come in Longitude, Latitude order
df_swapped = pd.DataFrame({
    COL_POINT_ID:  ["B01", "B02", "B03", "B04", "B05", "B06"],
    COL_LONGITUDE: [80.275721, 80.275900, 80.275500, 80.275300, 80.275600, 80.276000],
    COL_LATITUDE:  [13.082701, 13.082900, 13.082500, 13.082300, 13.082100, 13.082400],
})

lons = df_swapped[COL_LONGITUDE].tolist()
lats = df_swapped[COL_LATITUDE].tolist()

# CORRECT call (current code)
e_correct, n_correct = t.transform(lons, lats)
coords_correct = list(zip(e_correct, n_correct))
ring_correct = LinearRing(coords_correct + [coords_correct[0]])
print(f"\nCorrect call transform(lons, lats) → ring.is_simple={ring_correct.is_simple}")

# SWAPPED call (Lat/Lon reversed)
e_swapped, n_swapped = t.transform(lats, lons)
coords_swapped = list(zip(e_swapped, n_swapped))
ring_swapped = LinearRing(coords_swapped + [coords_swapped[0]])
print(f"Swapped call transform(lats, lons) → ring.is_simple={ring_swapped.is_simple}")
if not ring_swapped.is_simple:
    print(f"  {explain_validity(ring_swapped)}")

print("\n── Conclusion ──────────────────────────────────────────────────")
print("The conversion axis order (always_xy=True, passing lon first) is CORRECT.")
print("The self-intersection must come from a different cause.")
print("\nChecking: does _convert_latlon_to_utm preserve input row order?")

# Check that reset_index after dropna preserves order
df_with_none = pd.DataFrame({
    COL_POINT_ID:  ["B01", "B02", None, "B04"],
    COL_LATITUDE:  [13.08, 13.09, None, 13.07],
    COL_LONGITUDE: [80.27, 80.28, None, 80.26],
})
clean = df_with_none.dropna(subset=[COL_LATITUDE, COL_LONGITUDE])
print(f"\ndf with None row: index before reset = {list(clean.index)}")
result = clean[[COL_POINT_ID]].copy().reset_index(drop=True)
e2, n2 = t.transform(clean[COL_LONGITUDE].tolist(), clean[COL_LATITUDE].tolist())
result[COL_EASTING]  = list(e2)
result[COL_NORTHING] = list(n2)
print(f"After reset_index: Point_IDs = {result[COL_POINT_ID].tolist()}")
print("Row order preserved: B01, B02, B04 (B03 dropped) ✓")
