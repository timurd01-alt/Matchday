import json
import tempfile
import unittest
from pathlib import Path

import fetch_data
import refresh_ncaaf_venues as venues
from provider_adapters import ProviderError


def _row(name, lat, lon, city="", state=""):
    return {"name": name, "latitude": lat, "longitude": lon,
            "dome": False, "city": city, "state": state}


class _Adapter:
    """Stand-in for CollegeFootballDataAdapter.venues()."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def venues(self):
        self.calls += 1
        return self.rows


def _slate(extra=()):
    # Enough distinct venues to clear MINIMUM_DURABLE_COVERAGE.
    rows = [_row(f"Stadium {index}", 30.0 + index * 0.01, -90.0, f"City{index}")
            for index in range(venues.MINIMUM_DURABLE_COVERAGE + 5)]
    rows.extend(extra)
    return rows


class NormalizationTests(unittest.TestCase):
    def test_normalize_keeps_the_disambiguating_qualifier(self):
        self.assertEqual(venues.normalize("Memorial Stadium (Lincoln, NE)"),
                         "memorial stadium lincoln ne")

    def test_strip_qualifier_and_city_are_separable(self):
        name = "Memorial Stadium (Champaign, IL)"
        self.assertEqual(venues.strip_qualifier(name), "memorial stadium")
        self.assertEqual(venues.qualifier_city(name), "champaign")

    def test_unqualified_name_has_no_city(self):
        self.assertEqual(venues.qualifier_city("Husky Stadium"), "")


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = str(Path(self.dir.name) / "venues.json")

    def test_shared_names_are_excluded_rather_than_guessed(self):
        # Three real, distant grounds all called "Husky Stadium".
        adapter = _Adapter(_slate([
            _row("Husky Stadium", 47.6503, -122.3016, "Seattle", "WA"),
            _row("Husky Stadium", 29.6949, -95.5167, "Houston", "TX"),
            _row("Husky Stadium", 45.5616, -94.1642, "Saint Cloud", "MN"),
        ]))
        venues.refresh_if_missing(adapter=adapter, path=self.path)
        by_name_city, by_name = venues.load(self.path)
        self.assertNotIn("husky stadium", by_name)
        # The city-qualified keys still resolve each one individually.
        self.assertEqual(by_name_city["husky stadium|seattle"], (47.6503, -122.3016))

    def test_qualified_names_stay_distinct(self):
        adapter = _Adapter(_slate([
            _row("Memorial Stadium (Lincoln, NE)", 40.8207, -96.7056, "Lincoln", "NE"),
            _row("Memorial Stadium (Champaign, IL)", 40.0993, -88.2360, "Champaign", "IL"),
        ]))
        venues.refresh_if_missing(adapter=adapter, path=self.path)
        _, by_name = venues.load(self.path)
        self.assertEqual(by_name["memorial stadium lincoln ne"], (40.8207, -96.7056))
        self.assertEqual(by_name["memorial stadium champaign il"], (40.0993, -88.2360))

    def test_duplicate_rows_for_one_site_are_not_treated_as_ambiguous(self):
        adapter = _Adapter(_slate([
            _row("Shared Ground", 40.0000, -90.0000, "Town", "IL"),
            _row("Shared Ground", 40.0050, -90.0050, "Town", "IL"),
        ]))
        venues.refresh_if_missing(adapter=adapter, path=self.path)
        _, by_name = venues.load(self.path)
        self.assertIn("shared ground", by_name)

    def test_refresh_is_skipped_once_durable(self):
        adapter = _Adapter(_slate())
        venues.refresh_if_missing(adapter=adapter, path=self.path)
        venues.refresh_if_missing(adapter=adapter, path=self.path)
        self.assertEqual(adapter.calls, 1)

    def test_empty_provider_response_raises_rather_than_persisting(self):
        with self.assertRaises(ProviderError):
            venues.refresh_if_missing(adapter=_Adapter([]), path=self.path)
        self.assertFalse(Path(self.path).exists())

    def test_rows_without_usable_coordinates_never_reach_the_file(self):
        adapter = _Adapter(_slate([_row("No Fix Stadium", None, None, "Nowhere")]))
        venues.refresh_if_missing(adapter=adapter, path=self.path)
        _, by_name = venues.load(self.path)
        self.assertNotIn("no fix stadium", by_name)

    def test_a_foreign_schema_version_loads_as_empty(self):
        Path(self.path).write_text(json.dumps(
            {"schema_version": venues.SCHEMA_VERSION + 1,
             "by_name": {"x": [1, 2]}, "by_name_city": {}}), encoding="utf-8")
        self.assertEqual(venues.load(self.path), ({}, {}))


class VenueLookupTests(unittest.TestCase):
    def setUp(self):
        self._comp = fetch_data.COMP_KEY
        self._cache = fetch_data._COLLEGE_VENUE_COORDS
        self.addCleanup(self._restore)

    def _restore(self):
        fetch_data.COMP_KEY = self._comp
        fetch_data._COLLEGE_VENUE_COORDS = self._cache

    def _install(self, by_name, by_name_city=None):
        fetch_data._COLLEGE_VENUE_COORDS = (by_name_city or {}, by_name)

    def test_college_exact_match_beats_the_substring_table(self):
        # "Memorial Stadium (Lincoln, NE)" contains the curated "lincoln"
        # keyword, which is Lincoln Financial Field in Philadelphia.
        fetch_data.COMP_KEY = "NCAAF"
        self._install({"memorial stadium lincoln ne": (40.8207, -96.7056)})
        self.assertEqual(fetch_data.venue_coords("Memorial Stadium (Lincoln, NE)"),
                         (40.8207, -96.7056))

    def test_pro_competitions_never_consult_the_college_file(self):
        fetch_data.COMP_KEY = "MLB"
        self._install({"wrigley field": (41.8756, -87.6244)})
        self.assertEqual(fetch_data.venue_coords("Wrigley Field"),
                         fetch_data.VENUE_COORDS["wrigley"])

    def test_unresolvable_shared_name_yields_no_coordinates(self):
        fetch_data.COMP_KEY = "NCAAF"
        self._install({})
        self.assertIsNone(fetch_data.venue_coords("Husky Stadium"))

    def test_college_falls_back_to_the_curated_table(self):
        fetch_data.COMP_KEY = "NCAAF"
        self._install({})
        self.assertEqual(fetch_data.venue_coords("Mercedes-Benz Stadium"),
                         fetch_data.VENUE_COORDS["mercedes"])


if __name__ == "__main__":
    unittest.main()
