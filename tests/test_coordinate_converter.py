"""
tests/test_coordinate_converter.py
------------------------------------
Unit tests for location/coordinate_converter.py.

Tests cover:
- Format detection (lat/lon vs projected)
- CRS validation (valid and invalid strings)
- Single-point projected → geographic conversion
- Coordinate range validation
- Centroid extraction from lat/lon DataFrame
- Centroid conversion from projected DataFrame
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd

from location.coordinate_converter import (
    ConversionResult,
    CoordinateConversionError,
    InvalidCRSError,
    InvalidCoordinateRangeError,
    convert_dataframe_to_latlon,
    convert_projected_to_latlon,
    detect_coordinate_format,
    extract_latlon_from_dataframe,
    validate_crs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def projected_df() -> pd.DataFrame:
    """Four-point survey DataFrame with Easting/Northing (UTM zone 44N)."""
    return pd.DataFrame({
        "Point_ID": ["B01", "B02", "B03", "B04"],
        "Easting":  [518980.691, 518964.561, 518950.123, 518960.789],
        "Northing": [2350645.822, 2350654.358, 2350630.100, 2350610.456],
    })


@pytest.fixture
def latlon_df() -> pd.DataFrame:
    """Four-point survey DataFrame with Latitude/Longitude."""
    return pd.DataFrame({
        "Point_ID":  ["B01", "B02", "B03", "B04"],
        "Latitude":  [13.082701, 13.082900, 13.082500, 13.082300],
        "Longitude": [80.275721, 80.275900, 80.275500, 80.275300],
    })


@pytest.fixture
def latlon_alias_df() -> pd.DataFrame:
    """DataFrame using 'Lat'/'Lon' alias headers."""
    return pd.DataFrame({
        "Point_ID": ["A01", "A02", "A03"],
        "Lat":  [13.0, 13.1, 13.2],
        "Lon":  [80.0, 80.1, 80.2],
    })


# ---------------------------------------------------------------------------
# detect_coordinate_format
# ---------------------------------------------------------------------------

class TestDetectCoordinateFormat:

    def test_projected_detected(self, projected_df):
        assert detect_coordinate_format(projected_df) == "projected"

    def test_latlon_detected(self, latlon_df):
        assert detect_coordinate_format(latlon_df) == "latlon"

    def test_latlon_alias_detected(self, latlon_alias_df):
        assert detect_coordinate_format(latlon_alias_df) == "latlon"

    def test_case_insensitive_lat(self):
        df = pd.DataFrame({
            "Point_ID": ["X01", "X02", "X03"],
            "LAT": [1.0, 2.0, 3.0],
            "LON": [4.0, 5.0, 6.0],
        })
        assert detect_coordinate_format(df) == "latlon"

    def test_only_latitude_column_returns_projected(self):
        """A file with only Latitude but not Longitude is treated as projected."""
        df = pd.DataFrame({
            "Point_ID": ["X01", "X02", "X03"],
            "Latitude": [1.0, 2.0, 3.0],
            "Easting":  [100.0, 200.0, 300.0],
        })
        assert detect_coordinate_format(df) == "projected"


# ---------------------------------------------------------------------------
# validate_crs
# ---------------------------------------------------------------------------

class TestValidateCRS:

    def test_valid_epsg_32644(self):
        crs = validate_crs("EPSG:32644")
        assert "UTM zone 44N" in crs.name

    def test_valid_epsg_4326(self):
        crs = validate_crs("EPSG:4326")
        assert crs is not None

    def test_invalid_epsg_raises(self):
        with pytest.raises(InvalidCRSError, match="valid CRS"):
            validate_crs("EPSG:99999")

    def test_garbage_string_raises(self):
        with pytest.raises(InvalidCRSError):
            validate_crs("NOT_A_CRS")

    def test_empty_string_raises(self):
        with pytest.raises(InvalidCRSError):
            validate_crs("")


# ---------------------------------------------------------------------------
# convert_projected_to_latlon
# ---------------------------------------------------------------------------

class TestConvertProjectedToLatlon:

    def test_utm_44n_conversion_produces_valid_range(self):
        lat, lon = convert_projected_to_latlon(518980.691, 2350645.822, "EPSG:32644")
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180

    def test_utm_43n_conversion(self):
        lat, lon = convert_projected_to_latlon(400000.0, 1500000.0, "EPSG:32643")
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180

    def test_invalid_crs_raises(self):
        with pytest.raises(InvalidCRSError):
            convert_projected_to_latlon(518980.0, 2350645.0, "EPSG:99999")

    def test_extremely_wrong_values_raise_range_error(self):
        """Coordinates that produce nonsense lat/lon after conversion."""
        with pytest.raises(InvalidCoordinateRangeError):
            # Y value so large it produces latitude > 90 after transform
            convert_projected_to_latlon(500000.0, 99_999_999.0, "EPSG:32644")


# ---------------------------------------------------------------------------
# extract_latlon_from_dataframe
# ---------------------------------------------------------------------------

class TestExtractLatLonFromDataframe:

    def test_centroid_within_input_range(self, latlon_df):
        result: ConversionResult = extract_latlon_from_dataframe(latlon_df)
        lats = latlon_df["Latitude"].tolist()
        lons = latlon_df["Longitude"].tolist()
        assert min(lats) <= result.latitude <= max(lats)
        assert min(lons) <= result.longitude <= max(lons)

    def test_was_converted_is_false(self, latlon_df):
        result = extract_latlon_from_dataframe(latlon_df)
        assert result.was_converted is False

    def test_source_crs_is_4326(self, latlon_df):
        result = extract_latlon_from_dataframe(latlon_df)
        assert result.source_crs == "EPSG:4326"

    def test_point_count_matches_rows(self, latlon_df):
        result = extract_latlon_from_dataframe(latlon_df)
        assert result.point_count == len(latlon_df)

    def test_alias_columns_resolved(self, latlon_alias_df):
        result = extract_latlon_from_dataframe(latlon_alias_df)
        assert result.point_count == 3

    def test_missing_latlon_columns_raises(self, projected_df):
        with pytest.raises(CoordinateConversionError):
            extract_latlon_from_dataframe(projected_df)

    def test_out_of_range_lat_raises(self):
        df = pd.DataFrame({
            "Point_ID": ["X01", "X02", "X03"],
            "Latitude":  [200.0, 201.0, 202.0],   # invalid
            "Longitude": [80.0,  80.1,  80.2],
        })
        with pytest.raises(InvalidCoordinateRangeError):
            extract_latlon_from_dataframe(df)


# ---------------------------------------------------------------------------
# convert_dataframe_to_latlon
# ---------------------------------------------------------------------------

class TestConvertDataframeToLatlon:

    def test_centroid_in_valid_range(self, projected_df):
        result: ConversionResult = convert_dataframe_to_latlon(
            projected_df, "EPSG:32644"
        )
        assert -90 <= result.latitude <= 90
        assert -180 <= result.longitude <= 180

    def test_was_converted_is_true(self, projected_df):
        result = convert_dataframe_to_latlon(projected_df, "EPSG:32644")
        assert result.was_converted is True

    def test_source_crs_recorded(self, projected_df):
        result = convert_dataframe_to_latlon(projected_df, "EPSG:32644")
        assert result.source_crs == "EPSG:32644"

    def test_point_count_matches(self, projected_df):
        result = convert_dataframe_to_latlon(projected_df, "EPSG:32644")
        assert result.point_count == len(projected_df)

    def test_invalid_crs_raises(self, projected_df):
        with pytest.raises(InvalidCRSError):
            convert_dataframe_to_latlon(projected_df, "EPSG:99999")

    def test_empty_dataframe_raises(self):
        empty = pd.DataFrame({"Point_ID": [], "Easting": [], "Northing": []})
        with pytest.raises(CoordinateConversionError, match="No valid"):
            convert_dataframe_to_latlon(empty, "EPSG:32644")
