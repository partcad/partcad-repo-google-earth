#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The repository plugin of '//pub/collection/google-earth': a place in Google Earth, as parts.

A part here is a reference: a kind and where, and nothing else -

    elevation;lat=38.729300,lon=-77.107400,size=400
    surface;lat=38.729300,lon=-77.107400,resolution=0.5,size=400x300
    tiles;lat=38.729300,lon=-77.107400,size=400

- and is made, when it is built, from Google's data, fetched with the key of
whoever builds it ('pc login //pub/collection/google-earth:google_earth_repo'),
under the terms that key was given on. Nothing of Google's is in the package or
in this script, and the package says '"persist": false', so PartCAD keeps what
this answers in memory for the run and not on disk; every part says
'cache: false', so what is built of it is not kept either.

  * 'elevation': the ground, from the Elevation API, 'samples' heights along
    the longer side - a 'heightmap' part: a solid, a box below and the ground
    on top.
  * 'surface': what Google Earth shows standing there, buildings and trees
    included, from the Photorealistic 3D Tiles: the highest point of the mesh
    over each 'resolution' metres, read from tiles of at most 'error' metres'
    geometric error - a 'heightmap' part too, drawn as 'tiles'.
  * 'tiles': the 3D tiles' mesh itself, in the place's frame - a 'gltf' part, a
    surface and not a solid, which is why 'surface' is the part to place and
    this is what it is drawn as.

'lat' and 'lon' are the middle of the place, in degrees; 'size' its width and
depth in metres (one number for a square). 'base' is the 'heightmap' type's own,
in millimetres: how far above z = 0 the lowest of the surface stands. A search ('pc search parts -k
"Mount Vernon"') geocodes the words with the Geocoding API and answers with the
three parts of the place found.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import earth  # noqa: E402

CACHE_VERSION = 1

USER_AGENT = "partcad-repo-google-earth/1 (+https://github.com/partcad/partcad)"

KINDS = ("elevation", "surface", "tiles")

TERMS = "https://cloud.google.com/maps-platform/terms"
ATTRIBUTION = (
    "Map data and imagery: Google. Fetched with your own Google Maps Platform key, under its terms (%s)." % TERMS
)

CONSOLE = "https://console.cloud.google.com"
CREDENTIALS = CONSOLE + "/google/maps-apis/credentials"
BILLING = CONSOLE + "/billing/linkedaccount"
LOGIN = "pc login //pub/collection/google-earth:google_earth_repo"

# The APIs a key is used with: what each is for here, the Cloud service that is it, and whether a part needs it.
# Every part needs its data; only a search needs a place's name made a place.
APIS = (
    ("Elevation API", "elevation-backend.googleapis.com", "the ground ('elevation' parts)", True),
    ("Map Tiles API", "tile.googleapis.com", "what stands on it ('surface' and 'tiles' parts)", True),
    ("Geocoding API", "geocoding-backend.googleapis.com", "finding a place by its name ('pc search')", False),
)

KEY_INSTRUCTIONS = (
    "A Google Maps Platform API key of your own, from a Google Cloud project with billing: in the Google Cloud "
    "console (%s), pick or create a project, enable the Elevation API, the Map Tiles API and the Geocoding API "
    "for it, create an API key (Create credentials, API key), and restrict it to those three APIs. Its use is "
    "under Google's terms (%s), which you accept for yourself. The key can also be given as GOOGLE_MAPS_API_KEY "
    "in the environment the plugin runs in." % (CREDENTIALS, TERMS)
)


def http(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:2000].decode("utf-8", "replace")
        reason = None
        try:
            for detail in json.loads(body).get("error", {}).get("details", []):
                reason = reason or detail.get("reason")
        except (ValueError, AttributeError):
            pass
        raise earth.EarthError(
            "Google answered HTTP %d for %s%s" % (e.code, url.split("?")[0], " (%s)" % reason if reason else ""),
            status=e.code,
            reason=reason,
        )
    except (urllib.error.URLError, OSError) as e:
        raise earth.EarthError("Google could not be reached at %s: %s" % (url.split("?")[0], e), status="UNREACHABLE")


def api_key(request):
    key = ((request.get("parameters") or {}).get("api_key") or os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
    if not key:
        raise earth.EarthError(
            "no Google Maps Platform key: run 'pc login //pub/collection/google-earth:google_earth_repo'. "
            + KEY_INSTRUCTIONS
        )
    return key


# -- Names and declarations --------------------------------------------------------------------------------------
#
# A name's parameters are the place's and, for the surface and the mesh, how
# finely it is read. None of them is a parameter of the part type the part is
# built as: a 'heightmap' reads 'cell' and 'base' in millimetres, and a part's
# 'visual:' is asked for with the part's own values of every parameter it
# declares, so a name parameter that meant something else under the same name
# would reach the 'tiles' visual of a 'surface' as the wrong number.

PLACE = ("lat", "lon", "size")
OWN = {"elevation": ("samples",), "surface": ("resolution", "error", "base"), "tiles": ("resolution", "error", "base")}
DEFAULTS = {"size": "300", "samples": 64, "resolution": 1.0, "error": 1.0, "base": 1000.0}


def size_of(text):
    values = [float(v) for v in re.split(r"[x*]", str(text).lower()) if v.strip()]
    if len(values) == 1:
        values *= 2
    if len(values) != 2 or not all(0.0 < v <= 5000.0 for v in values):
        raise earth.EarthError("'size' is W or WxD in metres, each more than nothing and at most 5000: not '%s'" % text)
    return values


def place_of(kind, parameters):
    """What a name of 'kind' says, every value checked: {lat, lon, size} and the kind's own ('OWN')."""
    values = dict(DEFAULTS)
    values.update({k: v for k, v in (parameters or {}).items() if v not in (None, "")})
    if "lat" not in values or "lon" not in values:
        raise earth.EarthError("a place is named by its middle: give 'lat' and 'lon', in degrees")
    try:
        place = {"lat": float(values["lat"]), "lon": float(values["lon"]), "size": size_of(values["size"])}
        for name in OWN[kind]:
            place[name] = int(float(values[name])) if name == "samples" else float(values[name])
    except ValueError as e:
        raise earth.EarthError("a parameter of the place is not a number: %s" % e)
    if not (-85.0 < place["lat"] < 85.0 and -180.0 <= place["lon"] <= 180.0):
        raise earth.EarthError("'lat' is between -85 and 85, and 'lon' between -180 and 180")
    if "samples" in place and not (2 <= place["samples"] <= 512):
        raise earth.EarthError("'samples' is from 2 to 512 heights along the longer side")
    if "resolution" in place and not (0.1 <= place["resolution"] <= 50.0):
        raise earth.EarthError("'resolution' is from 0.1 to 50 m")
    if "error" in place and not (0.1 <= place["error"] <= 100.0):
        raise earth.EarthError("'error' is from 0.1 to 100 m")
    if "base" in place and not (0.0 <= place["base"] <= 1e6):
        raise earth.EarthError("'base' is from 0 to 1000000 mm")
    return place


def slug(kind, place):
    """The path a part's file is served at: every value that makes it, and nothing PartCAD would escape."""
    width, depth = place["size"]
    items = ["lat=%.6f" % place["lat"], "lon=%.6f" % place["lon"], "size=%gx%g" % (width, depth)]
    items += ["%s=%g" % (name, place[name]) for name in OWN[kind]]
    return "%s/%s.%s" % (kind, "_".join(items), "glb" if kind == "tiles" else "npy")


def parse_slug(path):
    kind, _, rest = path.partition("/")
    if kind not in KINDS:
        raise earth.EarthError("no file '%s' here" % path)
    stem = rest[: -len(".glb")] if kind == "tiles" else rest[: -len(".npy")]
    values = dict(item.split("=", 1) for item in stem.split("_") if "=" in item)
    return kind, place_of(kind, values)


def elevation_cell(place):
    """The Elevation API grid's cell, (x, y) in mm: what 'earth.elevation_grid' samples at."""
    width, depth = place["size"]
    step = max(width, depth) / float(place["samples"])
    return (width / max(2, int(round(width / step))) * 1000.0, depth / max(2, int(round(depth / step))) * 1000.0)


def declaration(kind, parameters):
    """The part a name is: its parameters' values as the name gives them, and the part type's own."""
    place = place_of(kind, parameters)
    width, depth = place["size"]
    where = "%g x %g m around %.6f, %.6f" % (width, depth, place["lat"], place["lon"])
    stated = {
        "lat": {"type": "float", "default": place["lat"], "desc": "The middle of the place: its latitude, degrees."},
        "lon": {"type": "float", "default": place["lon"], "desc": "The middle of the place: its longitude, degrees."},
        "size": {"type": "string", "default": "%gx%g" % (width, depth), "desc": "Its width x depth, metres."},
    }
    common = {
        "url": earth.earth_url(place["lat"], place["lon"], place["size"]),
        "manufacturable": False,
        # Google's data, fetched with the user's key: what is built of it is not kept.
        "cache": False,
        "path": slug(kind, place),
    }
    if kind == "elevation":
        stated["samples"] = {"type": "int", "default": place["samples"], "desc": "Heights along the longer side."}
        # The 'heightmap' type's own: the file's heights are metres, a sample every 'cell' mm.
        stated["unit"] = {"type": "string", "default": "m"}
        stated["cell"] = {"type": "string", "default": "%g %g" % elevation_cell(place)}
        return dict(
            common,
            type="heightmap",
            desc="The ground of %s, from Google's Elevation API. %s" % (where, ATTRIBUTION),
            parameters=stated,
        )
    stated["resolution"] = {
        "type": "float",
        "default": place["resolution"],
        "desc": "The surface model's cell, metres.",
    }
    stated["error"] = {"type": "float", "default": place["error"], "desc": "The 3D tiles' geometric error, metres."}
    # Shared with the 'heightmap' type, in its meaning: mm from z = 0 to the lowest of the surface.
    stated["base"] = {"type": "float", "default": place["base"], "desc": "mm from z = 0 to the lowest of it."}
    if kind == "tiles":
        return dict(
            common,
            type="gltf",
            desc="Google Earth's 3D mesh of %s (Photorealistic 3D Tiles): a surface, not a solid. %s"
            % (where, ATTRIBUTION),
            parameters=stated,
        )
    stated["unit"] = {"type": "string", "default": "m"}
    stated["cell"] = {"type": "float", "default": place["resolution"] * 1000.0}
    return dict(
        common,
        type="heightmap",
        desc="What stands on %s as Google Earth shows it - buildings and trees included - as a solid: the highest "
        "point of the 3D tiles over each %g m. %s" % (where, place["resolution"], ATTRIBUTION),
        # Drawn as the mesh it was made from, asked for with this part's own place, resolution, error and base.
        visual="tiles",
        parameters=stated,
    )


def file_of(path, key):
    """The bytes of a part's file: Google's data over the place, fetched now."""
    import numpy

    kind, place = parse_slug(path)
    if kind == "elevation":
        heights, _ = earth.elevation_grid(place["lat"], place["lon"], place["size"], place["samples"], key, http)
        return earth.npy(heights)
    frame = earth.Frame(place["lat"], place["lon"])
    radius = 0.5 * (place["size"][0] ** 2 + place["size"][1] ** 2) ** 0.5
    meshes = earth.tile_meshes(place["lat"], place["lon"], radius, place["error"], key, http)
    positions, triangles = earth.clipped(*earth.in_frame(meshes, frame), place["size"])
    if not len(triangles):
        raise earth.EarthError("Google's 3D tiles have nothing over this place")
    top = earth.rasterize(positions, triangles, place["size"], place["resolution"])
    if numpy.isnan(top).all():
        raise earth.EarthError("Google's 3D tiles cover none of this place")
    if kind == "surface":
        return earth.npy(top)
    # The datum the surface's 'heightmap' puts at 'base': the lowest of the surface model, which the
    # mesh may dip below between its cells' middles - by a little, and never below z = 0.
    lowest = float(numpy.nanmin(top))
    placed = positions - numpy.array([0.0, 0.0, lowest - place["base"] / 1000.0])
    placed[:, 2] = numpy.maximum(placed[:, 2], 0.0)
    return earth.write_glb(placed, triangles)


def search(text, limit, key):
    hits = {}
    for name, lat, lon in earth.geocode(text, key, http)[: max(1, limit // len(KINDS))]:
        for kind in KINDS:
            parameters = {"lat": "%.6f" % lat, "lon": "%.6f" % lon, "size": DEFAULTS["size"]}
            declared = declaration(kind, parameters)
            declared["desc"] = "%s: %s" % (name, declared["desc"])
            hits["%s;lat=%s,lon=%s,size=%s" % (kind, parameters["lat"], parameters["lon"], parameters["size"])] = (
                declared
            )
    return hits


META = {
    "desc": "Places in Google Earth, as parts: the ground from Google's Elevation API, and what stands on it from "
    "Google's Photorealistic 3D Tiles, each fetched with your own Google Maps Platform key when it is built. "
    + ATTRIBUTION,
    "url": "https://earth.google.com",
    "manufacturable": False,
    "objectKinds": ["part"],
    "instanceKinds": ["part"],
    "searchKinds": ["part"],
    # Kept for the run, never on disk: Google's terms limit keeping what is fetched.
    "persist": False,
}


def query_of(request):
    """The key taken apart: as PartCAD sends it, or as PartCAD's own toolkit reads the key."""
    query = request.get("query")
    if isinstance(query, dict) and "what" in query:
        return query
    import plugin_models

    return plugin_models.query_of(request.get("key", ""))


def get(request):
    query = query_of(request)
    what = query.get("what")
    if what == "meta":
        return dict(META)
    if what == "deps":
        return []
    if what == "objects":
        if query.get("kind") != "part":
            return {}
        return {kind: declaration(kind, {"lat": 0.0, "lon": 0.0}) for kind in KINDS}
    if what == "object":
        if query.get("kind") != "part" or query.get("name") not in KINDS:
            return None
        return declaration(query["name"], query.get("parameters") or {"lat": 0.0, "lon": 0.0})
    if what == "search":
        if query.get("kind") != "part":
            return {}
        return search(query.get("text") or "", int(query.get("limit") or 9), api_key(request))
    if what == "file":
        return earth.b64(file_of(query.get("path") or "", api_key(request)))
    return None


# -- Logging in ----------------------------------------------------------------------------------------------------
#
# A key is enough for Google to say which of its APIs it can use, and why not: so 'pc login' asks each of the
# three, says what is missing and where to fix it, and walks the user through the console where they have none.


def library(service):
    return "%s/apis/library/%s" % (CONSOLE, service)


def ask_api(name, key):
    """Ask one API one cheap question with the key: the EarthError Google answered, or None if it answered."""
    try:
        if name == "Elevation API":
            earth.elevations([(0.0, 0.0)], key, http)
        elif name == "Geocoding API":
            earth.geocode("Greenwich", key, http)
        else:
            http(earth._with_key(earth.TILES_ROOT, key, None))
    except earth.EarthError as e:
        return e
    return None


def problem(name, service, error):
    """(what is wrong, how to fix it) for an API's answer to a key: what a person can act on, with the page."""
    status, reason = str(error.status or ""), str(error.reason or "")
    said = reason.lower()
    if status == "UNREACHABLE":
        return "unreachable", "Google could not be reached: %s" % error
    if reason in ("API_KEY_INVALID",) or "api key is invalid" in said or "api key not valid" in said:
        return "invalid", "Google does not know the key: make one at %s" % CREDENTIALS
    if reason == "SERVICE_DISABLED" or "not activated" in said or "has not been used" in said or "is disabled" in said:
        return "disabled", "it is not enabled for the key's project: enable it at %s" % library(service)
    if reason == "API_KEY_SERVICE_BLOCKED" or "not authorized to use this service" in said:
        return "restricted", "the key's API restrictions leave it out: allow it on the key at %s" % CREDENTIALS
    if reason == "BILLING_DISABLED" or "billing" in said or status == "OVER_DAILY_LIMIT":
        return "billing", "the key's project has no billing account: link one at %s" % BILLING
    if status in ("OVER_QUERY_LIMIT", "429") or reason == "RATE_LIMIT_EXCEEDED":
        return "quota", "it is over its quota just now: try again shortly"
    return "denied", (
        "Google refuses the key for it (%s): enable it for the key's project at %s, allow it in the key's API "
        "restrictions at %s, and check that the project has billing"
        % (reason or status or error, library(service), CREDENTIALS)
    )


def diagnose(key):
    """[(api, service, purpose, required, None or (kind, fix))] for each API the plugin uses."""
    found = []
    for name, service, purpose, required in APIS:
        error = ask_api(name, key)
        found.append((name, service, purpose, required, problem(name, service, error) if error else None))
    return found


def report(found):
    """What the key cannot do yet, a line an API - or one line, when every API says the same - or ''."""
    failing = [f for f in found if f[4]]
    if len(failing) > 1 and len(failing) == len(found) and len({f[4] for f in failing}) == 1:
        return "  every API: %s" % failing[0][4][1]
    return "\n".join("  %s, for %s: %s" % (name, purpose, fix) for name, _, purpose, _, (kind, fix) in failing)


def usable(found):
    """Whether every API a part needs answers the key."""
    return all(problem is None for _, _, _, required, problem in found if required)


def guide_steps():
    """What the browser spotlights on the console's pages, step by step, while the user sets the key up."""
    steps = []
    for name, service, purpose, _ in APIS:
        steps.append(
            {
                "url": library(service) + "*",
                "selector": "button",
                "contains": r"^\s*Enable\s*$",
                "text": "Enable the %s, for %s. Then open the next API, or Credentials." % (name, purpose),
            }
        )
    for page in (CREDENTIALS, CONSOLE + "/apis/credentials"):
        steps.append(
            {
                "url": page + "*",
                "selector": "button",
                "contains": r"Create credentials",
                "text": "Create an API key (or use one you have), restrict it to the Elevation, Map Tiles and "
                "Geocoding APIs, and paste it in the bar above.",
            }
        )
    return steps


def instructions_for(key, found):
    """What to do, in words, for whoever has no browser: the key's state where there is one, and the steps."""
    lines = []
    if key and found:
        missing = report(found)
        if missing:
            lines.append("The key you have cannot be used yet:\n" + missing)
    lines.append(KEY_INSTRUCTIONS)
    lines.append(
        "Enable each API at its page: %s."
        % ", ".join("%s %s" % (name, library(service)) for name, service, _, _ in APIS)
    )
    return "\n\n".join(lines)


def outcome(key, found, how):
    """The login's answer for a key Google was asked about: saved, with what is still missing, or refused."""
    if usable(found):
        missing = report(found)
        message = "%s: Google takes the key for the Elevation and Map Tiles APIs" % how
        if missing:
            message += "; not yet for:\n" + missing
        return {"parameters": {"api_key": key}, "message": message}
    raise earth.EarthError(
        "Google does not take the key yet for:\n%s\n\nFix those in the Google Cloud console, then run '%s' again "
        "(or hand the key over with '%s --set api_key=<key>')." % (report(found), LOGIN, LOGIN)
    )


def login(request, partcad_login):
    """'pc login': the key there is, if Google takes it; else the console, walked through, and the key it gives.

    Before the browser is asked for, only what the key there is says decides
    anything: the browser's answer is replayed into a run from the top (see
    PartCAD's 'plugin_login'), so this must ask for it the same way each time.
    """
    key = ((request.get("parameters") or {}).get("api_key") or os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
    found = diagnose(key) if key else []
    if key and usable(found):
        return outcome(key, found, "Logged in")
    if key and getattr(partcad_login, "check", False):
        return outcome(key, found, "Logged in")  # a check opens nothing: it says what is missing
    invalid = any(f[4] and f[4][0] == "invalid" for f in found)
    first = next((f for f in found if f[4] and f[4][0] == "disabled"), None)
    # Where to start: the first API to enable, for a key Google knows; making a key, for none.
    url = library(first[1]) if (key and not invalid and first) else CREDENTIALS
    got = partcad_login.open_browser(
        url=url,
        title="Google Maps Platform",
        capture=[
            {
                "name": "api_key",
                "ask": {"label": "Your Google Maps Platform API key, once its APIs are enabled", "secret": True},
                # A Google API key: 'AIza' and 35 more. Anything else pasted there is not one.
                "match": r"^AIza[0-9A-Za-z_\-]{35}$",
            }
        ],
        guide=guide_steps(),
        instructions=instructions_for(key, found),
        timeout=1800,
    )
    key = (got.get("api_key") or "").strip()
    return outcome(key, diagnose(key), "Logged in")


if __name__ in ("get", "login"):
    _request = globals().get("request") or {}
    try:
        if __name__ == "login":
            output = {"result": login(_request, globals().get("partcad_login"))}
        else:
            output = {"result": get(_request)}
    except earth.EarthError as e:
        output = {"exception": str(e)}
