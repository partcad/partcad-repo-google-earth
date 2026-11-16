#
# partcad-repo-google-earth, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests of the plugin: what PartCAD is answered, with Google answered by the tests.

The plugin is run the way PartCAD runs it - the script, with 'request' and
'partcad_login' in its globals and its '__name__' the api - for what needs no
Google; and its functions are called, with its 'http' replaced, for what does.
"""

import base64
import io
import json
import os
import re
import runpy
import urllib.parse

import numpy
import plugin_login
import pytest
import test_earth
from test_earth import LAT, LON

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(_HERE, "google_earth_repo.py")
# The globals its functions read: 'run_path' answers with a copy, where replacing 'http' would change nothing.
plugin = runpy.run_path(SCRIPT, run_name="google_earth_repo_under_test")["get"].__globals__


def run(api, request, partcad_login=None):
    """The script run as PartCAD runs it (see PartCAD's 'wrappers/wrapper_plugin.py'): its 'output'."""
    init = {"request": request}
    if partcad_login is not None:
        init["partcad_login"] = partcad_login
    return runpy.run_path(SCRIPT, init_globals=init, run_name=api)["output"]


@pytest.fixture(autouse=True)
def no_key_of_the_machine(monkeypatch):
    """A key in the environment the tests run in is somebody's: no test reads it, or asks Google with it."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)


class Asked(list):
    """The URLs the plugin asked, and what each API is to refuse the key with: {api: refusal}."""

    def __init__(self):
        super().__init__()
        self.refuse = {}


# How Google refuses a key, in its own shapes: a Maps web service's answer, and the Map Tiles API's error.
NOT_ACTIVATED = {
    "status": "REQUEST_DENIED",
    "error_message": "This API is not activated on your API project. You may need to enable this API in the Google "
    "Cloud Console: https://console.cloud.google.com/apis/library?filter=category:maps.",
    "results": [],
}
NOT_AUTHORIZED = {
    "status": "REQUEST_DENIED",
    "error_message": "This API key is not authorized to use this service or API. Please check the API restrictions "
    "settings of your API key in the Google Cloud Console.",
    "results": [],
}
INVALID = {"status": "REQUEST_DENIED", "error_message": "The provided API key is invalid. ", "results": []}


def tiles_refusal(code, reason):
    def refuse():
        raise plugin["earth"].EarthError("Google answered HTTP %d" % code, status=code, reason=reason)

    return refuse


def google_fixture(monkeypatch):
    elevation, tiles, asked = test_earth.Elevation(), test_earth.Tiles(), Asked()

    def http(url):
        asked.append(url)
        host = urllib.parse.urlsplit(url).netloc
        for api, prefix in (
            ("Elevation API", plugin["earth"].ELEVATION_API),
            ("Geocoding API", plugin["earth"].GEOCODING_API),
            ("Map Tiles API", "https://tile.googleapis.com/"),
        ):
            refusal = asked.refuse.get(api)
            if refusal is not None and url.startswith(prefix):
                return refusal() if callable(refusal) else json.dumps(refusal).encode()
        if url.startswith(plugin["earth"].ELEVATION_API):
            return elevation(url)
        if url.startswith(plugin["earth"].GEOCODING_API):
            found = {
                "formatted_address": "Mount Vernon, VA 22121, USA",
                "geometry": {"location": {"lat": LAT, "lng": LON}},
            }
            return json.dumps({"results": [found], "status": "OK"}).encode()
        assert host == "tile.googleapis.com", url
        return tiles(url)

    monkeypatch.setitem(plugin, "http", http)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("the network was asked: %s" % (a,)))
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    return asked


@pytest.fixture
def google(monkeypatch):
    """The plugin's 'http', answered by whichever of the tests' Googles a URL is for."""
    return google_fixture(monkeypatch)


def name_of(base, parameters):
    """A name as PartCAD spells it: the parameters sorted by name."""
    return base + ";" + ",".join("%s=%s" % item for item in sorted(parameters.items()))


def test_the_package_says_what_it_serves_and_that_none_of_it_is_kept():
    meta = run("get", {"key": "meta", "query": {"what": "meta"}})["result"]
    assert meta["objectKinds"] == meta["instanceKinds"] == meta["searchKinds"] == ["part"]
    assert meta["persist"] is False and meta["manufacturable"] is False
    # A key not taken apart is read as PartCAD reads it.
    listed = run("get", {"key": "objects/part"})["result"]
    assert sorted(listed) == ["elevation", "surface", "tiles"]
    assert {name: config["type"] for name, config in listed.items()} == {
        "elevation": "heightmap",
        "surface": "heightmap",
        "tiles": "gltf",
    }
    assert all(config["cache"] is False for config in listed.values())


def test_an_instance_is_the_place_its_name_says():
    parameters = {"lat": "38.708300", "lon": "-77.086300", "size": "400x300", "samples": "40"}
    key = "objects/part/" + name_of("elevation", parameters)
    query = {"what": "object", "kind": "part", "name": "elevation", "parameters": parameters}
    declared = run("get", {"key": key, "query": query})["result"]
    assert declared["type"] == "heightmap" and declared["cache"] is False and declared["manufacturable"] is False
    assert declared["path"] == "elevation/lat=38.708300_lon=-77.086300_size=400x300_samples=40.npy"
    values = {name: p["default"] for name, p in declared["parameters"].items()}
    assert values["lat"] == pytest.approx(38.7083) and values["size"] == "400x300" and values["unit"] == "m"
    # A sample every 10 m along the longer side, and the shorter divided as evenly: what the grid is asked at.
    assert values["cell"] == "10000 10000"
    assert declared["url"].startswith("https://earth.google.com/web/@38.708300,-77.086300,")
    assert "Google" in declared["desc"] and "terms" in declared["desc"]


@pytest.mark.parametrize(
    "parameters, words",
    [
        ({"lon": "-77"}, "give 'lat' and 'lon'"),
        ({"lat": "95", "lon": "0"}, "'lat' is between"),
        ({"lat": "1", "lon": "1", "size": "9000"}, "at most 5000"),
        ({"lat": "1", "lon": "1", "samples": "1"}, "'samples' is from 2"),
        ({"lat": "north", "lon": "1"}, "not a number"),
    ],
)
def test_a_name_that_says_no_place_is_refused_with_why(parameters, words):
    query = {"what": "object", "kind": "part", "name": "elevation", "parameters": parameters}
    output = run("get", {"key": "objects/part/elevation;x=1", "query": query})
    assert "result" not in output and words in output["exception"]


def test_a_surface_is_drawn_as_the_tiles_of_its_own_place():
    """A visual is asked for with the part's values of every parameter the visual declares (PartCAD's 'visual')."""
    surface = plugin["declaration"]("surface", {"lat": LAT, "lon": LON, "size": "30", "resolution": "0.5", "base": 500})
    assert surface["type"] == "heightmap" and surface["visual"] == "tiles"
    values = {name: p["default"] for name, p in surface["parameters"].items()}
    # The 'heightmap' type's own, in its own units: a cell of half a metre, the lowest 500 mm above z = 0.
    assert values["cell"] == pytest.approx(500.0) and values["base"] == pytest.approx(500.0) and values["unit"] == "m"
    declared = plugin["declaration"]("tiles", {"lat": 0.0, "lon": 0.0})["parameters"]
    asked = {name: values[name] for name in declared}
    tiles = plugin["declaration"]("tiles", asked)
    assert tiles["type"] == "gltf"
    assert tiles["path"].rsplit(".", 1)[0].split("/", 1)[1] == surface["path"].rsplit(".", 1)[0].split("/", 1)[1]
    assert {"cell", "unit"}.isdisjoint(declared)


def test_the_ground_is_fetched_with_the_key_and_served_as_an_array(google):
    path = "elevation/lat=%.6f_lon=%.6f_size=200x100_samples=20.npy" % (LAT, LON)
    request = {"key": "files/" + path, "parameters": {"api_key": "the-key"}}
    data = plugin["get"](dict(request, query={"what": "file", "path": path}))
    heights = numpy.load(io.BytesIO(base64.b64decode(data)), allow_pickle=False)
    assert heights.shape == (10, 20) and heights.dtype == numpy.float32
    assert heights[0, 0] > heights[-1, 0]
    assert all("key=the-key" in url for url in google)


def test_without_a_key_nothing_is_fetched_and_the_user_is_told_how(google):
    path = "elevation/lat=%.6f_lon=%.6f_size=200x100_samples=20.npy" % (LAT, LON)
    with pytest.raises(plugin["earth"].EarthError, match="pc login //pub/collection/google-earth:google_earth_repo"):
        plugin["get"]({"key": "files/" + path, "query": {"what": "file", "path": path}, "parameters": {}})
    assert google == []


def test_the_surface_and_its_tiles_stand_on_one_datum(google):
    place = {"lat": LAT, "lon": LON, "size": "30", "resolution": "1", "error": "1", "base": "500"}
    surface = plugin["declaration"]("surface", place)["path"]
    tiles = plugin["declaration"]("tiles", place)["path"]
    top = numpy.load(io.BytesIO(plugin["file_of"](surface, "the-key")), allow_pickle=False)
    assert top.shape == (30, 30) and not numpy.isnan(top).any()
    # The square slopes up 0.1 m a metre east, from 0 at x = -20: the lowest cell's middle is x = -14.5.
    assert float(top.min()) == pytest.approx(0.55, abs=1e-5)
    ((positions, _),) = plugin["earth"].glb_meshes(plugin["file_of"](tiles, "the-key"))
    z = positions[:, 1]  # glTF is Y up
    # The heightmap puts the lowest of the surface model at 'base', 0.5 m: so does the mesh, whose highest
    # corner is 4 m. Its lowest, 0.55 m below the lowest cell's middle, would be below z = 0, and stops there.
    assert float(z.max()) == pytest.approx(0.5 + 4.0 - 0.55, abs=1e-5)
    assert float(z.min()) == 0.0


def test_a_search_finds_a_place_by_its_name(google):
    request = {"key": "search/part?q=Mount+Vernon", "parameters": {"api_key": "the-key"}}
    hits = plugin["get"](dict(request, query={"what": "search", "kind": "part", "text": "Mount Vernon", "limit": 9}))
    assert sorted(name.split(";")[0] for name in hits) == ["elevation", "surface", "tiles"]
    name = next(name for name in hits if name.startswith("surface;"))
    assert name == name_of("surface", {"lat": "%.6f" % LAT, "lon": "%.6f" % LON, "size": "300"})
    assert hits[name]["desc"].startswith("Mount Vernon, VA 22121, USA: ")
    assert any(url.startswith(plugin["earth"].GEOCODING_API) for url in google)


def test_a_key_google_takes_is_kept(google):
    result = plugin["login"]({"parameters": {"api_key": "the-key"}}, plugin_login.LoginCallback({}))
    assert result["parameters"] == {"api_key": "the-key"}
    assert "Elevation and Map Tiles" in result["message"] and "not yet" not in result["message"]
    # Each API was asked, once.
    assert sum(url.startswith(plugin["earth"].ELEVATION_API) for url in google) == 1
    assert sum(url.startswith(plugin["earth"].GEOCODING_API) for url in google) == 1
    assert sum("3dtiles/root.json" in url for url in google) == 1


def test_a_key_from_the_environment_is_kept(google, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "the-key")
    result = plugin["login"]({"parameters": {}}, plugin_login.LoginCallback({}))
    assert result["parameters"] == {"api_key": "the-key"}


@pytest.mark.parametrize(
    "status, reason, kind, page",
    [
        (
            "REQUEST_DENIED",
            NOT_ACTIVATED["error_message"],
            "disabled",
            "/apis/library/elevation-backend.googleapis.com",
        ),
        ("REQUEST_DENIED", NOT_AUTHORIZED["error_message"], "restricted", "/google/maps-apis/credentials"),
        ("REQUEST_DENIED", INVALID["error_message"], "invalid", "/google/maps-apis/credentials"),
        ("REQUEST_DENIED", "You must enable Billing on the Google Cloud Project", "billing", "/billing/"),
        (403, "SERVICE_DISABLED", "disabled", "/apis/library/elevation-backend.googleapis.com"),
        (403, "API_KEY_SERVICE_BLOCKED", "restricted", "/google/maps-apis/credentials"),
        (400, "API_KEY_INVALID", "invalid", "/google/maps-apis/credentials"),
        (403, "BILLING_DISABLED", "billing", "/billing/"),
        (403, "ACCESS_DENIED", "denied", "/apis/library/elevation-backend.googleapis.com"),
        ("OVER_QUERY_LIMIT", "", "quota", None),
        ("UNREACHABLE", "", "unreachable", None),
    ],
)
def test_each_refusal_is_said_with_where_to_fix_it(status, reason, kind, page):
    error = plugin["earth"].EarthError("refused", status=status, reason=reason)
    found_kind, fix = plugin["problem"]("Elevation API", "elevation-backend.googleapis.com", error)
    assert found_kind == kind
    if page:
        assert page in fix


def test_google_s_error_body_is_read_for_its_reason(monkeypatch):
    import io
    import urllib.error

    body = json.dumps(
        {
            "error": {
                "code": 403,
                "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED"}],
            }
        }
    ).encode()

    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(body))

    monkeypatch.setattr(plugin["urllib"].request, "urlopen", refuse)
    with pytest.raises(plugin["earth"].EarthError) as e:
        plugin["http"]("https://tile.googleapis.com/v1/3dtiles/root.json?key=the-key")
    assert e.value.status == 403 and e.value.reason == "SERVICE_DISABLED"
    assert "the-key" not in str(e.value)


def test_a_key_that_cannot_search_yet_is_kept_and_says_so(google):
    google.refuse["Geocoding API"] = NOT_AUTHORIZED
    result = plugin["login"]({"parameters": {"api_key": "the-key"}}, plugin_login.LoginCallback({}))
    assert result["parameters"] == {"api_key": "the-key"}
    assert "Geocoding API" in result["message"] and "restrictions" in result["message"]


def test_a_check_says_what_the_key_cannot_do_and_opens_nothing(google):
    google.refuse["Map Tiles API"] = tiles_refusal(403, "SERVICE_DISABLED")
    with pytest.raises(plugin["earth"].EarthError) as e:
        plugin["login"]({"parameters": {"api_key": "the-key"}}, plugin_login.LoginCallback({"check": True}))
    said = str(e.value)
    assert "Map Tiles API" in said and "/apis/library/tile.googleapis.com" in said
    assert "Elevation API" not in said


def test_a_key_with_an_api_to_enable_is_walked_to_that_api(google):
    google.refuse["Elevation API"] = NOT_ACTIVATED
    with pytest.raises(plugin_login.BrowserNeeded) as e:
        plugin["login"]({"parameters": {"api_key": "the-key"}}, plugin_login.LoginCallback({}))
    assert e.value.spec["url"].endswith("/apis/library/elevation-backend.googleapis.com")


def test_a_key_google_does_not_know_is_walked_to_making_one(google):
    for api in ("Elevation API", "Geocoding API"):
        google.refuse[api] = INVALID
    google.refuse["Map Tiles API"] = tiles_refusal(400, "API_KEY_INVALID")
    with pytest.raises(plugin_login.BrowserNeeded) as e:
        plugin["login"]({"parameters": {"api_key": "the-key"}}, plugin_login.LoginCallback({}))
    assert e.value.spec["url"].endswith("/google/maps-apis/credentials")


def test_without_a_key_the_browser_is_asked_for_one_and_shown_the_way():
    with pytest.raises(plugin_login.BrowserNeeded) as e:
        run("login", {"parameters": {}}, plugin_login.LoginCallback({}))
    spec = e.value.spec
    assert spec["url"] == "https://console.cloud.google.com/google/maps-apis/credentials"
    (capture,) = spec["capture"]
    assert capture["name"] == "api_key" and capture["ask"]["secret"] is True
    # Only a Google API key is taken for one.
    pattern = re.compile(capture["match"])
    assert pattern.match("AIza" + "x" * 35) and not pattern.match("the-key")
    # A step on each API's page and on the credentials page, each pointing at its button.
    pages = [step["url"] for step in spec["guide"]]
    for service in ("elevation-backend", "tile", "geocoding-backend"):
        assert any("/apis/library/%s.googleapis.com" % service in page for page in pages)
    assert any("/credentials" in page for page in pages)


def test_with_nobody_at_the_screen_the_user_is_told_where_a_key_is_made():
    with pytest.raises(plugin_login.InstructionsNeeded) as e:
        run("login", {"parameters": {}}, plugin_login.LoginCallback({"non_interactive": True}))
    said = e.value.spec["instructions"]
    assert "Elevation API" in said and "terms" in said
    assert "/apis/library/tile.googleapis.com" in said and "GOOGLE_MAPS_API_KEY" in said


def test_with_nobody_at_the_screen_a_key_s_problems_come_first(google):
    google.refuse["Elevation API"] = NOT_ACTIVATED
    with pytest.raises(plugin_login.InstructionsNeeded) as e:
        plugin["login"]({"parameters": {"api_key": "the-key"}}, plugin_login.LoginCallback({"non_interactive": True}))
    said = e.value.spec["instructions"]
    assert said.startswith("The key you have cannot be used yet") and "elevation-backend" in said


def test_the_key_the_browser_brings_back_is_checked_and_kept(google):
    login = plugin_login.LoginCallback({"browser": [{"api_key": " the-key "}]})
    result = plugin["login"]({"parameters": {}}, login)
    assert result["parameters"] == {"api_key": "the-key"} and "Logged in" in result["message"]
    assert any(url.startswith(plugin["earth"].ELEVATION_API) for url in google)


def test_a_key_handed_over_that_google_refuses_is_not_kept(google):
    for api in ("Elevation API", "Geocoding API"):
        google.refuse[api] = INVALID
    google.refuse["Map Tiles API"] = tiles_refusal(400, "API_KEY_INVALID")
    with pytest.raises(plugin["earth"].EarthError) as e:
        plugin["login"]({"parameters": {}}, plugin_login.LoginCallback({"values": {"api_key": "AIza" + "0" * 35}}))
    # Every API says the same, so it is said once.
    assert "every API: Google does not know the key" in str(e.value) and "--set api_key=" in str(e.value)
