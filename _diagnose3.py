"""
Final targeted diagnosis.

The actual survey file that was working with E/N format now fails
with Lat/Lon. The only difference is the conversion layer.

Key question: does the _convert_latlon_to_utm function correctly
assign converted coordinates back to the RIGHT Point_ID rows?

The current code:
    clean = df.dropna(subset=[COL_LATITUDE, COL_LONGITUDE])
    ...
    result = clean[[COL_POINT_ID]].copy().reset_index(drop=True)
    result[COL_EASTING]  = list(eastings)   # positional assignment
    result[COL_NORTHING] = list(northings)

After _normalise_latlon_columns, df already has a clean 0-based
integer index (it does .copy() on a sliced df).
After dropna the index still has the original integer labels (no gaps
if no NaN rows exist). reset_index(drop=True) then gives 0..N-1.
list(eastings) is also 0..N-1 positionally.

So for a file with NO missing rows, this is CORRECT.

The self-intersection with valid data means the problem is NOT in the
conversion ordering. The real issue is that the original survey was
designed as a closed non-convex boundary where the point ORDER matters.
When the SAME points are uploaded in Lat/Lon format, the order is
preserved — so it cannot be a reordering issue.

ACTUAL ROOT CAUSE: The Transformer returns arrays in the same order as
the input. The input comes from clean[COL_LONGITUDE].tolist() which
follows the DataFrame row order. So the order IS correct.

But wait — let's check what happens if the original survey file uses
a DIFFERENT column ordering that triggers a Northing/Easting swap at
the _normalise_latlon_columns stage, not in pyproj.

Look at _normalise_latlon_columns:
    df = df[[COL_POINT_ID, COL_LATITUDE, COL_LONGITUDE]].copy()
    df[COL_LATITUDE]  = pd.to_numeric(df[COL_LATITUDE],  errors="coerce")
    df[COL_LONGITUDE] = pd.to_numeric(df[COL_LONGITUDE], errors="coerce")

This is correct. But what if the UPLOAD has columns labeled:
    Point | Northing | Easting   (in that column ORDER in the file)

and _detect_columns sees has_easting=True, has_northing=True
→ routes to Format A (easting_northing path)
→ _normalise_columns grabs Easting and Northing correctly

No issue there.

FINAL HYPOTHESIS: The self-intersection is triggered because
Transformer.transform() with always_xy=True is being called with
NUMPY ARRAYS returned by .tolist()... wait, .tolist() returns Python
lists, that's fine.

Let's try the ACTUAL failure scenario: a real survey boundary that
self-intersects when the point ORDER is preserved through conversion.
This would mean the original survey was a valid polygon in E/N
coordinates, but the SAME points in Lat/Lon upload produce a
self-intersecting polygon — which is impossible if the conversion is
a pure bijection.

Therefore: the self-intersection existed in the ORIGINAL file too,
but was only introduced (or unmasked) by the new code path.

CHECK: Does _detect_columns have an ambiguity where a Lat/Lon file
could be routed to the E/N path, causing Latitude to be treated as
Easting and Longitude as Northing?
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from config import COLUMN_ALIASES, LATLON_ALIASES, COL_EASTING, COL_NORTHING, COL_LATITUDE, COL_LONGITUDE

# Build the exact lower-case sets used in _detect_columns
easting_checks  = {COL_EASTING.lower(), "east", "e", "x"}
northing_checks = {COL_NORTHING.lower(), "north", "n", "y"}
lat_checks = {k.lower() for k, v in LATLON_ALIASES.items() if v == COL_LATITUDE}
lon_checks = {k.lower() for k, v in LATLON_ALIASES.items() if v == COL_LONGITUDE}

print("Easting detection set: ", sorted(easting_checks))
print("Northing detection set:", sorted(northing_checks))
print("Latitude detection set:", sorted(lat_checks))
print("Longitude detection set:", sorted(lon_checks))

# KEY OVERLAP CHECK
overlap_lat_north = lat_checks & northing_checks
overlap_lon_east  = lon_checks & easting_checks
print(f"\nOverlap lat_checks ∩ northing_checks: {overlap_lat_north}")
print(f"Overlap lon_checks ∩ easting_checks:  {overlap_lon_east}")

# Simulate a file with columns: Point, Latitude, Longitude
cols = ["point", "latitude", "longitude"]
has_easting  = bool(set(cols) & easting_checks)
has_northing = bool(set(cols) & northing_checks)
has_lat      = bool(set(cols) & lat_checks)
has_lon      = bool(set(cols) & lon_checks)
print(f"\nFile with ['point','latitude','longitude']:")
print(f"  has_easting={has_easting}, has_northing={has_northing}")
print(f"  has_lat={has_lat}, has_lon={has_lon}")

# Check: does "n" in northing_checks collide with anything in a lat/lon file?
# "n" is in northing_checks. Is "n" a column name in any common lat/lon export? No.
# But what about the col "northing" — does it appear in lat_checks?
print(f"\n'northing' in lat_checks: {'northing' in lat_checks}")
print(f"'n' in lat_checks: {'n' in lat_checks}")
print(f"'latitude' in easting_checks: {'latitude' in easting_checks}")

print("\n── The detection logic is unambiguous for standard column names ──")
print("The self-intersection is in the DATA (point ordering), not the code.")
print("\nChecking if Transformer.transform returns (easting, northing) correctly")
print("for a point known to produce a NORTHING larger than EASTING:")

from pyproj import Transformer
t = Transformer.from_crs("EPSG:4326", "EPSG:32644", always_xy=True)
# Chennai: lat=13, lon=80  →  E ≈ 420000, N ≈ 1437000
r = t.transform(80.0, 13.0)
print(f"  transform(lon=80, lat=13) → ({r[0]:.0f}, {r[1]:.0f})")
print(f"  r[0] = {r[0]:.0f}  ← must be EASTING  (< 1 000 000)")
print(f"  r[1] = {r[1]:.0f}  ← must be NORTHING (> 1 000 000)")

if r[0] < 1_000_000 and r[1] > 1_000_000:
    print("  ✓ Axis order confirmed correct: (easting, northing)")
    east_var, north_var = "eastings", "northings"
else:
    print("  ✗ AXIS SWAP DETECTED — r[0] is northing, r[1] is easting!")
    east_var, north_var = "WRONG", "WRONG"
    
print(f"\nIn _convert_latlon_to_utm:")
print(f"  eastings, northings = transformer.transform(lons, lats)")
print(f"  result[COL_EASTING]  = list(eastings)   # r[0] → {east_var}")
print(f"  result[COL_NORTHING] = list(northings)  # r[1] → {north_var}")
