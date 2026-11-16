# Google Earth for PartCAD

Places in Google Earth, as parts, published as `//pub/collection/google-earth`. A part here is
a **reference** to a place: its kind, its middle and its size, and nothing else. It is made when
it is built, from Google's data, fetched with **your own Google Maps Platform key**, under
Google's terms, which you accept for yourself when you get that key.

| Part | What it is | From | Built as |
| --- | --- | --- | --- |
| `elevation` | the ground | the [Elevation API](https://developers.google.com/maps/documentation/elevation) | a `heightmap`: a solid, a box below and the ground on top |
| `surface` | what stands there - buildings, trees - as Google Earth shows it | the [Photorealistic 3D Tiles](https://developers.google.com/maps/documentation/tile/3d-tiles) | a `heightmap`: the highest point of the mesh over each cell; drawn as `tiles` |
| `tiles` | Google Earth's mesh itself, in the place's frame | the Photorealistic 3D Tiles | a `gltf`: a surface, not a solid |

Each is one script, `google_earth_repo.py`, serving the package's external dependency `places`
(the protocol is PartCAD's repository plugin's; see "Repositories" in PartCAD's
`config_package.rst`). Every part is a solid you can place, measure, simulate and export -
`surface` is the one to put a scene on, and a picture of it is drawn with Google Earth's own
mesh (`visual: tiles`).

## Setting it up

```shell
pc login //pub/collection/google-earth:google_earth_repo
```

walks you through it. You need a Google Cloud project with billing, the **Elevation API** and the
**Map Tiles API** enabled for it (and the **Geocoding API**, for `pc search`), and an API key of
that project allowed to use them. `pc login`:

1. **asks Google about the key you have** - the one it saved before, or `GOOGLE_MAPS_API_KEY` in the
   environment the plugin runs in - one cheap request to each of the three APIs, and keeps it if
   the Elevation and Map Tiles APIs answer;
2. **otherwise opens the Google Cloud console** in PartCAD's browser - at the first API the key's
   project has not enabled, or at Credentials where there is no key Google knows - and points at
   what to press on each page: **Enable** on each API's page, **Create credentials** for a key. When
   you have one, paste it into PartCAD's bar (only a Google API key, `AIza...`, is taken);
3. **asks Google about that key**, and keeps it - or says, API by API, what is still wrong and the
   page that fixes it:

```text
Google does not take the key yet for:
  Elevation API, for the ground ('elevation' parts): it is not enabled for the key's project:
    enable it at https://console.cloud.google.com/apis/library/elevation-backend.googleapis.com
  Geocoding API, for finding a place by its name ('pc search'): the key's API restrictions leave
    it out: allow it on the key at https://console.cloud.google.com/google/maps-apis/credentials
```

A key the Geocoding API refuses is kept all the same, with that said: parts work, and only a
search waits for it.

`pc login --check` asks Google about the key you have and opens nothing. With nobody at the screen
(`pc login --agent`, or an agent through `pc mcp`), `pc login` prints the same steps and links,
with what is wrong with the key there is, and takes the key with `--set api_key=<key>`.

PartCAD keeps the key in your `~/.partcad/config.yaml`, never in a package. Every request sends it
to Google as the `key` parameter.

## Using it

A name says the place: `lat` and `lon`, its middle, in degrees; `size`, its width x depth in
metres (`300`, or `400x300`). Then, per part:

* `elevation`: `samples`, the heights along the longer side (64; 2 to 512).
* `surface` and `tiles`: `resolution`, the surface model's cell in metres (1); `error`, the
  coarsest geometric error of the tiles read, in metres (1); `base`, how far the lowest of the
  surface stands above z = 0, in **millimetres** (1000) - the `heightmap` type's own, in its
  own unit, so that the `tiles` a `surface` is drawn as stand where it does.

```shell
pc search parts -P //pub/collection/google-earth/places -k "Mount Vernon, Virginia"
pc inspect "//pub/collection/google-earth/places:surface;lat=38.708300,lon=-77.086300,size=300"
```

and, in a scene - `site.assy`:

```yaml
links:
  - part: //pub/collection/google-earth/places:surface;lat=38.708300,lon=-77.086300,resolution=0.5,size=300
    name: ground
    fixed: true
```

with `partcad.yaml` saying:

```yaml
scenes:
  site:
    type: assy
    path: site.assy
    gravity: [0, 0, -9.81]
```

Exported to MuJoCo, both `heightmap` parts are written as an `<hfield>`, which MuJoCo collides
with as the surface it is (see the `partcad-sim-mujoco` plugin).

## Google's terms

Nothing of Google's is in this package: a part is a reference until whoever builds it fetches
it, with their key. And nothing fetched is kept:

* the package's `meta` says `"persist": false`, so PartCAD keeps what this plugin answers in the
  memory of the process that fetched it and writes none of it to disk; a file it serves is
  written only because a part type reads a path, and is removed when the process exits;
* every part says `cache: false`, so what is built of it is not kept either.

Every part carries a link to the place in Google Earth (`url`) and Google's attribution
(`desc`); show it wherever you show the part.

## What it cannot do (yet)

* **No place fetched from Google yet.** `pc login`'s checks have been run against Google, with a
  key whose project had not yet enabled the APIs, which is how its refusals are worded here; the
  data requests are tested against tables in the shapes Google's documentation gives.
* **One mesh, no textures.** Google's tiles are textured; `tiles` is their geometry only.
* **At most 600 tiles a place** (`earth.MAX_TILES`): a few hundred metres at a metre's error.
  A larger place needs a larger `error`.
* The Elevation API is sampled at 400 points a request, each a billed request.

## Tests

```shell
pip install --no-deps partcad    # PartCAD's plugin toolkit: only its files are needed
pip install pytest numpy DracoPy==2.1.0
pytest
```

Nothing in them touches the network, and no key is needed: every request goes through one
function, which the tests answer from tables in the shapes Google's documentation gives. Without
DracoPy the one test of a Draco-compressed tile is skipped. CI runs them on every push and nightly,
against PartCAD's `devel`.

## License

Apache 2.0 (see `LICENSE`). The data is Google's, fetched with your key and kept nowhere: see `NOTICE`.
