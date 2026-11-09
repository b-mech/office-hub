from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

spec = spec_from_file_location("geocode_locations", Path(__file__).parents[1] / "scripts" / "geocode_locations.py")
g = module_from_spec(spec)
spec.loader.exec_module(g)


def result(road="Clubhouse Drive", house=None, city="Lorette"):
    a = dict(road=road, town=city, state="Manitoba", country_code="ca")
    if house:
        a["house_number"] = house
    return dict(lat="49.7468826", lon="-96.8943672", address=a)


def test_precision_requires_number_street_and_correct_community():
    assert g.classify(result(house="142"), "142 Clubhouse Drive", "Lorette")[0] == "house"
    assert g.classify(result(), "142 Clubhouse Drive", "Lorette")[0] == "street"
    assert g.classify(result(house="146"), "142 Clubhouse Drive", "Lorette")[0] == "street"
    assert g.classify(result(city="Winnipeg"), "142 Clubhouse Drive", "Lorette")[0] == "not_found"
    assert g.classify(result(road="Main Street"), "142 Clubhouse Drive", "Lorette")[0] == "not_found"


def test_locality_centroid_is_never_plottable():
    r = result()
    del r["address"]["road"]
    assert g.classify(r, "142 Clubhouse Drive", "Lorette")[0] == "locality"
    r["address"]["country_code"] = "us"
    assert g.classify(r, "142 Clubhouse Drive", "Lorette")[0] == "not_found"


def test_municipality_overrides_bad_default_city():
    assert g.query_address(dict(address="142 Clubhouse Drive", city="Winnipeg", municipality="Lorette"))[1] == "Lorette"
    assert g.query_address(dict(address="253 Blossom Way", community="PARKVIEW POINTE - PHASE 3", municipality="RM of West St. Paul"))[1] == "West St. Paul"
    assert g.query_address(dict(address="37 Ella Drive", community="Prairie View Lakes", municipality="RM of Macdonald"))[1] == "La Salle"


def test_bilingual_road_and_abbreviations():
    assert g.normalize("Avenue Guay Avenue") == g.normalize("Guay Ave")
    assert g.normalize("Regent Avenue East") != g.normalize("Regent Avenue West")


def test_identical_coordinates_downgrade_house_to_approximate():
    rows = [dict(address=a, latitude=49.8, longitude=-97.1, precision="house", reason="match") for a in ["142 Clubhouse Drive", "146 Clubhouse Drive"]]
    g.flag_clusters(rows)
    assert all(r["precision"] == "street" for r in rows)


def test_condo_house_is_never_unit_exact():
    assert g.classify(result(house="100"), "100 Clubhouse Drive", "Lorette", unit=True)[0] == "street"


def test_city_prefix_does_not_accept_another_town():
    assert g.classify(result(city="Winnipeg Beach"), "142 Clubhouse Drive", "Winnipeg")[0] == "not_found"


def test_multiple_distant_house_results_are_not_first_result_wins():
    coder = g.Geocoder.__new__(g.Geocoder)
    first = result(house="142")
    second = dict(first, lat="49.750000")
    coder.search = lambda street, city: [first, second]
    row = coder.locate(dict(address="142 Clubhouse Drive", municipality="Lorette"))
    assert row["precision"] == "not_found"
    assert row["latitude"] is None
    assert "ambiguous" in row["reason"]
