"""
tests/test_location_service.py
--------------------------------
Unit tests for location/location_service.py and reports/location_report.py.

Tests use unittest.mock to avoid real network calls so the suite runs
offline and deterministically.

Coverage:
- detect_location with lat/lon format (no CRS needed)
- detect_location with projected format + valid CRS
- detect_location with projected format + missing CRS
- detect_location with projected format + invalid CRS
- Geocoding failure demoted to warning (not fatal error)
- Network unavailable demoted to warning
- build_location_report output structure
- LocationReport field content
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd

from location.location_service import LocationResult, detect_location
from location.coordinate_converter import ConversionResult
from location.reverse_geocoder import GeocodingResult, NetworkUnavailableError
from reports.location_report import LocationReport, LocationReportRow, build_location_report


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def projected_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Point_ID": ["B01", "B02", "B03", "B04"],
        "Easting":  [518980.691, 518964.561, 518950.123, 518960.789],
        "Northing": [2350645.822, 2350654.358, 2350630.100, 2350610.456],
    })


@pytest.fixture
def latlon_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Point_ID":  ["B01", "B02", "B03", "B04"],
        "Latitude":  [13.082701, 13.082900, 13.082500, 13.082300],
        "Longitude": [80.275721, 80.275900, 80.275500, 80.275300],
    })


@pytest.fixture
def mock_geocoding_result() -> GeocodingResult:
    return GeocodingResult(
        latitude=13.0827,
        longitude=80.2757,
        display_name="Chennai, Tamil Nadu, India",
        country="India",
        state="Tamil Nadu",
        state_district="Chennai",
        city="Chennai",
        suburb="Royapuram",
        postcode="600001",
        road="Anna Salai",
        country_code="IN",
    )


# ---------------------------------------------------------------------------
# detect_location – lat/lon format
# ---------------------------------------------------------------------------

class TestDetectLocationLatLon:

    @patch("location.location_service.reverse_geocode")
    def test_succeeds_without_crs(self, mock_geocode, latlon_df, mock_geocoding_result):
        mock_geocode.return_value = mock_geocoding_result
        result = detect_location(latlon_df, source_crs=None)

        assert result.succeeded
        assert result.coordinate_format == "latlon"
        assert result.conversion is not None
        assert result.conversion.was_converted is False
        assert result.conversion.source_crs == "EPSG:4326"
        assert result.has_geocoding
        assert result.geocoding.country == "India"

    @patch("location.location_service.reverse_geocode")
    def test_google_maps_url_built(self, mock_geocode, latlon_df, mock_geocoding_result):
        mock_geocode.return_value = mock_geocoding_result
        result = detect_location(latlon_df)
        assert "google.com/maps" in result.google_maps_url
        assert "q=" in result.google_maps_url

    @patch("location.location_service.reverse_geocode")
    def test_crs_argument_ignored_for_latlon(self, mock_geocode, latlon_df, mock_geocoding_result):
        """Passing a CRS for a lat/lon file should not cause an error."""
        mock_geocode.return_value = mock_geocoding_result
        result = detect_location(latlon_df, source_crs="EPSG:32644")
        assert result.succeeded
        assert result.coordinate_format == "latlon"


# ---------------------------------------------------------------------------
# detect_location – projected format
# ---------------------------------------------------------------------------

class TestDetectLocationProjected:

    @patch("location.location_service.reverse_geocode")
    def test_succeeds_with_valid_crs(self, mock_geocode, projected_df, mock_geocoding_result):
        mock_geocode.return_value = mock_geocoding_result
        result = detect_location(projected_df, source_crs="EPSG:32644")

        assert result.succeeded
        assert result.coordinate_format == "projected"
        assert result.conversion is not None
        assert result.conversion.was_converted is True
        assert result.conversion.source_crs == "EPSG:32644"

    def test_fails_without_crs(self, projected_df):
        result = detect_location(projected_df, source_crs=None)

        assert not result.succeeded
        assert "CRS" in result.error or "Coordinate Reference System" in result.error

    def test_fails_with_invalid_crs(self, projected_df):
        result = detect_location(projected_df, source_crs="EPSG:99999")

        assert not result.succeeded
        assert "CRS" in result.error or "Invalid" in result.error

    @patch("location.location_service.reverse_geocode")
    def test_point_count_matches_rows(self, mock_geocode, projected_df, mock_geocoding_result):
        mock_geocode.return_value = mock_geocoding_result
        result = detect_location(projected_df, source_crs="EPSG:32644")
        assert result.conversion.point_count == len(projected_df)


# ---------------------------------------------------------------------------
# detect_location – geocoding failure handling
# ---------------------------------------------------------------------------

class TestGeocodingFailureHandling:

    @patch("location.location_service.reverse_geocode")
    def test_network_error_becomes_warning_not_fatal(self, mock_geocode, projected_df):
        mock_geocode.side_effect = NetworkUnavailableError("Connection refused")
        result = detect_location(projected_df, source_crs="EPSG:32644")

        # Pipeline should still succeed — coordinates are valid
        assert result.succeeded
        assert result.has_location
        assert not result.has_geocoding
        assert len(result.warnings) > 0
        assert any("geocod" in w.lower() for w in result.warnings)

    @patch("location.location_service.reverse_geocode")
    def test_generic_geocoder_error_becomes_warning(self, mock_geocode, latlon_df):
        from location.reverse_geocoder import ReverseGeocoderError
        mock_geocode.side_effect = ReverseGeocoderError("No result found")
        result = detect_location(latlon_df)

        assert result.succeeded
        assert not result.has_geocoding
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# LocationResult convenience properties
# ---------------------------------------------------------------------------

class TestLocationResultProperties:

    def test_has_location_true_when_conversion_present(self):
        conv = ConversionResult(
            latitude=13.08, longitude=80.27,
            source_crs="EPSG:4326", point_count=4, was_converted=False,
        )
        r = LocationResult(conversion=conv)
        assert r.has_location is True

    def test_has_location_false_when_no_conversion(self):
        r = LocationResult()
        assert r.has_location is False

    def test_succeeded_false_when_error_set(self):
        r = LocationResult(error="Something went wrong")
        assert r.succeeded is False

    def test_succeeded_true_when_no_error(self):
        r = LocationResult()
        assert r.succeeded is True

    def test_latitude_longitude_proxies(self):
        conv = ConversionResult(
            latitude=13.08, longitude=80.27,
            source_crs="EPSG:4326", point_count=1, was_converted=False,
        )
        r = LocationResult(conversion=conv)
        assert r.latitude == 13.08
        assert r.longitude == 80.27


# ---------------------------------------------------------------------------
# build_location_report
# ---------------------------------------------------------------------------

class TestBuildLocationReport:

    @pytest.fixture
    def full_result(self, mock_geocoding_result) -> LocationResult:
        conv = ConversionResult(
            latitude=13.082601,
            longitude=80.275721,
            source_crs="EPSG:4326",
            point_count=4,
            was_converted=False,
        )
        return LocationResult(
            coordinate_format="latlon",
            conversion=conv,
            geocoding=mock_geocoding_result,
            google_maps_url="https://www.google.com/maps?q=13.082601,80.275721",
        )

    @pytest.fixture
    def no_geocoding_result(self) -> LocationResult:
        conv = ConversionResult(
            latitude=13.082601,
            longitude=80.275721,
            source_crs="EPSG:32644",
            point_count=4,
            was_converted=True,
        )
        return LocationResult(
            coordinate_format="projected",
            conversion=conv,
            geocoding=None,
            google_maps_url="https://www.google.com/maps?q=13.082601,80.275721",
            warnings=["Geocoding unavailable"],
        )

    def test_returns_location_report_instance(self, full_result):
        report = build_location_report(full_result)
        assert isinstance(report, LocationReport)

    def test_latitude_longitude_formatted(self, full_result):
        report = build_location_report(full_result)
        assert report.latitude == "13.082601"
        assert report.longitude == "80.275721"

    def test_google_maps_url_preserved(self, full_result):
        report = build_location_report(full_result)
        assert "google.com/maps" in report.google_maps_url

    def test_has_geocoding_true(self, full_result):
        report = build_location_report(full_result)
        assert report.has_geocoding is True

    def test_rows_contain_all_expected_labels(self, full_result):
        report = build_location_report(full_result)
        labels = [r.label for r in report.rows]
        for expected in (
            "Latitude", "Longitude", "Country", "State",
            "District", "City / Town", "Area / Suburb",
            "Postal Code", "Nearest Landmark",
        ):
            assert expected in labels, f"Missing label: {expected}"

    def test_geocoding_values_populated(self, full_result):
        report = build_location_report(full_result)
        row_map = {r.label: r.value for r in report.rows}
        assert row_map["Country"] == "India"
        assert row_map["State"] == "Tamil Nadu"
        assert row_map["City / Town"] == "Chennai"
        assert row_map["Postal Code"] == "600001"

    def test_missing_geocoding_shows_placeholder(self, no_geocoding_result):
        report = build_location_report(no_geocoding_result)
        assert report.has_geocoding is False
        row_map = {r.label: r.value for r in report.rows}
        assert row_map["Country"] == "—"
        assert row_map["City / Town"] == "—"

    def test_coordinate_source_describes_conversion(self, no_geocoding_result):
        report = build_location_report(no_geocoding_result)
        assert "EPSG:32644" in report.coordinate_source
        assert "WGS84" in report.coordinate_source

    def test_coordinate_source_describes_direct_read(self, full_result):
        report = build_location_report(full_result)
        assert "directly" in report.coordinate_source.lower()

    def test_empty_result_does_not_raise(self):
        """build_location_report must never crash, even on an empty result."""
        empty = LocationResult()
        report = build_location_report(empty)
        assert isinstance(report, LocationReport)
        assert report.latitude == "—"
        assert report.longitude == "—"
