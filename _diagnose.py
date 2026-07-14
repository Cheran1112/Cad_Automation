"""
Diagnostic script – proves the self-intersection root cause.

Run from the cad_automation/ directory:
    python _diagnose.py

Demonstrates that dropna() on a DataFrame that already has a clean
integer index silently reorders rows when the original index was NOT
reset before the drop, leaving orphaned index labels that cause
reset_index(drop=True) to re-order the surviving rows incorrectly.

More critically, proves the actual bug:
    clean = df.dropna(...)          # preserves original index labels
    result = clean[[COL_POINT_ID]].copy().reset_index(drop=True)
    result[COL_EASTING]  = list(eastings)   # assigned positionally

The transformer returns values in the ORDER of clean's index.
reset_index(drop=True) renumbers 0..N-1 but does NOT change row order —
so this part is fine IF there are no missing rows.

The real culprit is that _normalise_latlon_columns() does:
    df = df[[COL_POINT_ID, COL_LATITUDE, COL_LONGITUDE]].copy()
    df[COL_LATITUDE]  = pd.to_numeric(..., errors="coerce")
    df[COL_LONGITUDE] = pd.to_numeric(..., errors="coerce")

pd.to_numeric with errors="coerce" operates correctly.
BUT — the Transformer.transform() call passes:
    clean[COL_LONGITUDE].tolist()
    clean[COL_LATITUDE].tolist()

With always_xy=True, pyproj expects  (x=longitude, y=latitude).
The transform() signature is transform(xx, yy) → (xx_out, yy_out).
So the call is:
    eastings, northings = transformer.transform(longitudes, latitudes)

That is CORRECT.  Let's verify what pyproj actually returns to make
sure easting/northing are not swapped.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from pyproj import Transformer

# Chennai survey sample points (Format B – Lat/Lon)
points = [
    ("B01", 13.082701, 80.275721),
    ("B02", 13.082900, 80.275900),
    ("B03", 13.082500, 80.275500),
    ("B04", 13.082300, 80.275300),
    ("B05", 13.082100, 80.275600),
    ("B06", 13.082400, 80.276000),
]

lats = [p[1] for p in points]
lons = [p[2] for p in points]

# Mean for UTM zone detection
mean_lat = sum(lats) / len(lats)
mean_lon = sum(lons) / len(lons)
zone_number = int((mean_lon + 180) / 6) + 1
epsg = f"EPSG:{32600 + zone_number}"
print(f"Mean lat={mean_lat:.6f}, lon={mean_lon:.6f}")
print(f"UTM zone {zone_number}N → {epsg}")

# always_xy=True means input order: (longitude, latitude)
t = Transformer.from_crs("EPSG:4326", epsg, always_xy=True)
eastings, northings = t.transform(lons, lats)

print("\nConverted points (in original row order):")
for i, (pid, lat, lon) in enumerate(points):
    print(f"  {pid}  lat={lat}  lon={lon}  →  E={eastings[i]:.3f}  N={northings[i]:.3f}")

# Now check what the CURRENT _convert_latlon_to_utm does with the result
import pandas as pd
from config import COL_POINT_ID, COL_EASTING, COL_NORTHING, COL_LATITUDE, COL_LONGITUDE

df = pd.DataFrame({
    COL_POINT_ID: [p[0] for p in points],
    COL_LATITUDE:  lats,
    COL_LONGITUDE: lons,
})

print(f"\nInput df index before dropna: {list(df.index)}")
clean = df.dropna(subset=[COL_LATITUDE, COL_LONGITUDE])
print(f"clean df index after dropna:  {list(clean.index)}")

east_list, north_list = t.transform(
    clean[COL_LONGITUDE].tolist(),
    clean[COL_LATITUDE].tolist(),
)

result = clean[[COL_POINT_ID]].copy().reset_index(drop=True)
result[COL_EASTING]  = list(east_list)
result[COL_NORTHING] = list(north_list)

print(f"\nResult df index after reset_index: {list(result.index)}")
print(f"Result Point_IDs in order: {result[COL_POINT_ID].tolist()}")
print("\nFinal converted DataFrame:")
print(result.to_string(index=True))

# Verify with Shapely – does this polygon self-intersect?
from shapely.geometry import LinearRing
coords = list(zip(result[COL_EASTING], result[COL_NORTHING]))
coords_closed = coords + [coords[0]]
ring = LinearRing(coords_closed)
print(f"\nShapely ring.is_simple = {ring.is_simple}")
if not ring.is_simple:
    from shapely.validation import explain_validity
    print(f"Validity: {explain_validity(ring)}")
    print("\n*** BUG CONFIRMED: polygon self-intersects after conversion ***")
else:
    print("Ring is simple (no self-intersection) — conversion is correct.")
