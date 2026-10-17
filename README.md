# THE MISSING MILLIONS

**What if the people missing from our maps are the people who need us most?**

A local geospatial investigation proof of concept: identify satellite-derived settlement candidates, inspect historical building signals and mapped healthcare access, compare an outreach scenario, and save evidence for human verification.

The application does not establish occupancy, medical need, missing real-world clinics, or operational feasibility. A priority score is a relative planning aid. Local organisations and communities must validate findings and participate in any service-planning decisions.

## Run locally

Requirements: Python 3.11 or newer, Node.js 20.19+ or 22.12+, npm, and a browser with WebGL. Initial dependency installation and optional source downloads need an internet connection. The prepared application has no hosting dependency, paid API subscription, or live Earth Engine requirement.

```bash
make setup
make prepare-demo   # Explicitly generates SYNTHETIC demonstration data.
make dev
```

Open [the application](http://127.0.0.1:5173). FastAPI's interactive API reference is at [localhost:8000/docs](http://127.0.0.1:8000/docs). Ctrl+C stops both development servers. Vite proxies `/api` to port 8000. A missing data package produces an explicit error; source failures never trigger an automatic synthetic replacement.

The map draws **Esri World Imagery satellite tiles** (© Esri, Maxar, Earthstar Geographics) beneath the local evidence layers; this is the only online-dependency in the interface and it can be switched off in **Map layers**, falling back to the offline dark canvas. All analysis layers, routing and scoring run from the local package with or without the imagery.

Optional settings are in `.env.example`. Copy it to `.env` to use them with `make dev`; existing shell variables take precedence. `DATA_PACKAGE_PATH` explicitly selects a single package; `TASKS_DB_PATH` selects the durable SQLite file. Direct `uvicorn` invocations read shell variables, not `.env` automatically.

For a single local server serving the built frontend:

```bash
make build
make serve
```

Then open [localhost:8000](http://127.0.0.1:8000). The map draws local GeoJSON on a schematic basemap; it does not pretend to be live satellite imagery. No remote basemap tiles are needed.

## Data modes and acquisition

Both processed packages have been built successfully in this checkout:

| Region | Prepared evidence | Candidate regions |
| --- | --- | --- |
| **Turkana source sample** (`turkana-real`) | Acquired Open Buildings 2016/2023, WorldPop 2023, and an OSM network/facility/settlement-registry snapshot for rural Turkana County, Kenya (35.72 °E, 3.18 °N) | 2 |
| **Mbale source sample** (`mbale-real`) | Acquired Open Buildings 2016/2023, WorldPop 2023, and a large OSM snapshot near Mbale, Uganda — kept as the dense urban comparison region | 2 |
| **Synthetic demonstration** (`turkana-demo`) | Explicit invented inputs with eight illustrative annual observations, 2016–2023, at a Turkana reference point | 42 |

The two real packages remain strictly separate: switch between them in the region selector to **compare settlement patterns, walk times and gap classifications** between a sparse rural area and a dense agricultural one. No records, scores or tasks are ever mixed across regions.

These counts describe the configured clustering output, not newly discovered communities or a count of people lacking healthcare. The compact real sample has only two candidates, so **its Isolation Forest analysis is disabled** below the minimum of 30. The 42-candidate synthetic fixture runs the full anomaly and stability demonstration. Its buildings, population, roads, facilities and annual observations are invented. **It is not a real discovery about Kenya.** The interface displays the selected data mode prominently.

The real acquisition covers a compact 10 km × 10 km Turkana County sample centred on 35.72 °E, 3.18 °N (rural Lodwar district, west of the A1), plus a 20 km road/facility/registry buffer — sized so the native 0.5 m count reads stay feasible on a laptop while sitting inside the spec's roughly 30 × 30 km envelope. Exact network and registry figures are in `data/raw/turkana-real/provenance.json` and the processed package manifest. Acquisition success and source provenance are recorded in `data/raw/turkana-real/acquisition-report.json`.

The application lists these separate packages through the region selector, preferring the real source sample by default. No records or measurements are mixed between modes. To expose exactly one mode, set `DATA_PACKAGE_PATH`. The prepared packages support browsing without repeating live downloads.

```bash
# Inspect real input availability without downloading; exit 2 means incomplete.
.venv/bin/python -m pipeline.ingest.acquire_sources --check

# Explicit public-source downloads (Turkana, Kenya). A failure is recorded, never replaced with fiction.
make acquire-real

# Build a distinct package only after compatible real inputs are available.
make prepare-real

# Optional: force the source-derived package instead of the package selector.
DATA_PACKAGE_PATH=data/processed/real.json make dev

# Optional: force the synthetic demonstration for the complete ML walkthrough.
DATA_PACKAGE_PATH=data/processed/demo.json make dev
```

See [data/README.md](data/README.md) for the raw-array contract, exact acquisition flags, CRS, count semantics, provenance, licensing and Earth Engine export alternative. The built-in acquisition path uses public Google Cloud Storage, WorldPop STAC and Overpass; it does not require Earth Engine credentials. A credentialed Earth Engine export requires an authorised Cloud project and `earthengine-api` authentication.

The source families are:

| Source | Use and interpretation |
| --- | --- |
| [Google Open Buildings 2.5D Temporal](https://sites.research.google/gr/open-buildings/temporal/) | Acquired native fractional building counts and presence for **2016 and 2023**. These are historical satellite-trained model predictions, not individual building polygons. Intermediate real observations were not acquired. |
| [WorldPop](https://hub.worldpop.org/) | Acquired **2023** Kenya Global2 constrained population counts, **R2025A v1** release. The 2025 release date does not change the 2023 reference year. |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Acquired mapped walking ways, general healthcare records and **mapped settlement registry records (`place=*`)** from a network snapshot retrieved **17 October 2026**. Retrieval does not make the records current or verify service availability. Registry completeness is unverified; absence from it is never evidence that a settlement is unknown. |

Credit Google Research and Copernicus Sentinel-2 under the selected CC BY 4.0 terms; WorldPop, University of Southampton, CC BY 4.0; and © OpenStreetMap contributors, ODbL 1.0. Check each package's manifest before redistributing source-derived outputs. No government partnership, predictive accuracy or medical outcome is claimed.

## What runs

The offline pipeline sums count evidence into projected 250 m analysis cells, groups supported cells with DBSCAN, assigns population without overlapping settlement totals, and computes growth only for available source years. Native raster count contributions are preserved. Analysis cells are displayed as cells, never fabricated building outlines. Clusters too small for confident analysis are **retained as sparse review signals** (flagged, never discarded) rather than filtered out.

**Settlement-registry comparison and gap classification.** Detection candidates are matched against an independently acquired mapped-settlement registry (`place=*` records, extractable from the OSM snapshot or importable as CSV/GeoJSON). Each candidate receives a match status — `matched`, `ambiguous`, `unmatched`, or `no_registry` — and a candidate gap category: **mapping gap** (habitation signal not confidently represented in the registry), **access gap** (a modelled journey beyond the 60-minute demonstration threshold), **combined gap**, or `none`. An unmatched candidate is *not* proof of an unknown village; the registry's completeness is never verified, and a missing registry makes gap classification `undetermined` rather than invented. The map shows recorded settlements as a separate reference layer.

**Human feedback that changes the result.** Local reviewers label a candidate `residential`, `non_residential` or `uncertain`, with notes, from the evidence panel. Labels never overwrite source evidence: a `non_residential` label removes the candidate's population weight and regional priorities are recomputed with the same transparent policy, so the ranking changes visibly with a recorded reason. Every comparison is an overlay; the original first-pass score stays visible.

**Active-learning review queue.** Unreviewed candidates are ranked by *investigation value* — regional priority × unresolved uncertainty (missing inputs, unknown routing, ambiguous registry representation, gap category). The queue names where one more local observation would change the most open conclusions. With enough recorded labels (≥10, two classes), a small logistic classifier trains on review labels and reports held-out accuracy with an explicit optimistic-bias warning.

**Interactive evidence response: a newly confirmed clinic.** A reviewer can confirm an additional operating facility (click the map while “Confirm new clinic” is armed). The API rebuilds routing with the confirmed record, recomputes every candidate's walking time and regional priority, and reports which candidates now reach recorded care sooner — as labelled overlays over unchanged source evidence.

**Access across the settlement, not just its centre.** The evidence panel measures the modelled walk time for every analysis cell of a candidate and reports the **median resident journey** and the **worst-tenth (p90) journey** next to the centroid estimate — for dense candidates the centre badly understates how far into the settlement some residents sit. Off-network cells are counted unknown, never imputed. These profiles are **precomputed into every processed package at build time** (`scripts/bench_access_profiles.py` reports an instant serve with no routing-engine build on an evidence-panel open; the medians are identical to a live routing run), so the 72 MB Mbale package opens its evidence instantly.

**Imagery-chip review.** The review box shows a live satellite crop centred on the candidate (© Esri World Imagery), so residential / non-residential / uncertain labels are grounded in what the reviewer is actually looking at. Tile responses are stored in the browser's **durable Cache API** after the first view, so revisited chips render from local storage even without a network; a chip never seen online degrades gracefully to field notes.

**Region comparison.** The header “Compare” button opens a side-by-side table of every prepared package — candidates, median and maximum modelled walks, gap-type mixes, registry size and in-extent recall — proving the same pipeline produces honest, region-specific different truths (sparse Turkana vs dense Mbale).

**Blind rediscovery test, live.** The data panel can withhold a chosen number of registry settlements and immediately check whether the satellite pipeline still covers them, with the disclosure that omissions are evaluation artifacts printed in the result.

**Printable investigation brief.** Any candidate can be opened as a one-page, print-styled brief (evidence rows, suggested verification task, caveats) — the artifact a local partner would actually take into the field.

Every number in the evidence panel now carries a hover provenance tooltip (dataset, model vintage, aggregation semantics).

**Evaluation CLI.** `python -m pipeline.evaluate` reports in-extent registry recall (share of registry settlements whose area the detector covered), top-candidate registry representation, and withheld-settlement recovery with explicit disclosure that omissions are evaluation artifacts, not discoveries.

Accessibility uses NetworkX shortest paths over the walking graph in a suitable projected UTM CRS. Both facility and settlement road connectors contribute to distances. The baseline is 4.2 km/h, with 3 and 5 km/h travel-time sensitivity estimates. Disconnected networks and connections beyond the configured limit remain unknown.

Isolation Forest uses log transforms, explicit missing indicators, median imputation, robust scaling, and five seeded model instances. Regional rank agreement is model stability, not calibrated confidence. The real sample's two candidates are insufficient for this analysis, so anomaly scores remain unavailable. The synthetic fixture's 42 candidates exercise the algorithm; those anomaly outputs describe synthetic inputs.

Priority combines regional percentiles of access, population, growth, mapping discrepancy and anomaly evidence with initial weights 35/25/15/15/10. Unknown access disables the overall score; other missing components make it provisional and contribute no points under the original weights. Weight perturbations expose ranking sensitivity. Current OSM building-discrepancy evidence is unavailable and is not invented.

Outreach simulation performs greedy, population-weighted maximum coverage over road nodes for one or two hypothetical stops. It evaluates incremental coverage above the mapped-facility baseline and includes settlement road connectors. The displayed coverage geometry is reachable road segments, not a fabricated walk-time polygon. Proposed stops need human review of road usability, safe space, local consent, services, staffing and permissions.

Drag the purple outreach marker to compare a manually chosen location. The point snaps to a mapped road node and recalculates the same baseline, scenario coverage, and per-settlement travel estimates. A manual location with zero incremental benefit is retained with **0** additional coverage; a disconnected settlement's route remains unknown. The API accepts `fixed_location: [longitude, latitude]` with `locations: 1` and rejects invalid WGS84 coordinates or points more than 1,500 metres from the mapped network.

Investigation tasks preserve a settlement evidence snapshot, geometry, uncertainty, questions, notes, status and optional hypothetical stop in SQLite. No task automatically edits OpenStreetMap.

## Judge walkthrough

Begin with the default **Turkana source sample** to inspect acquired evidence and its candidate regions. For the full Isolation Forest demonstration, select **Synthetic demonstration** and say explicitly that its measurements are illustrative. The two packages remain separate throughout the walkthrough.

1. Click **Start discovery**. Four scenes advance every 25 seconds, producing an approximately 100-second walkthrough. Pause or use the on-screen arrows and keyboard left/right arrows to control pacing.
2. Begin with mapped facilities and roads. **Reveal the overlooked** shows settlement candidates and historical building signals.
3. Open a candidate. Inspect population, walking route, actual available years, uncertainty, score components, and **How the AI works**.
4. Click **What if care went to them?** to calculate a hypothetical outreach stop. Compare baseline, scenario, and incremental population coverage. Drag the purple stop to recalculate a manual scenario, including an honest zero-gain result when appropriate. Change speed, threshold or number of stops in simulation settings to run optimisation again.
5. Create an investigation task, add local-review questions and notes, and inspect it in **Investigation tasks**. Change its status and export the saved evidence.
6. **Reset view** returns to the initial map; **Start discovery** replays the story.

Suggested closing: “We are building a way to ask better geographic questions before communities are left out of the decisions that affect them.”

## Verification and exports

```bash
make test       # Python geospatial, ML, routing, API and persistence tests.
make build      # TypeScript validation and production frontend build.

# Install a test browser once if needed, then run the browser journey.
npm --prefix apps/web exec -- playwright install chromium
make test-e2e
```

The latest local `make test` run passed **65 Python tests**: the original 48 covering count aggregation, clipping, non-overlap, clustering, historical growth, missing values, reproducible models, priority policy, route directionality, disconnected paths, both road connectors, incremental coverage, manual locations, API errors, complete stop evidence, lazy precomputed loading, and task persistence — plus 14 discovery→verification-loop tests (registry matching, gap classification, review recomputation, review queue, classifier boundary, confirmed-facility recomputation) and **3 new tests for the tier-1/2 surface** (per-cell access profiles with honest unknown cells, regional comparison aggregates, and the live blind test). **3 Playwright browser journeys also pass**, including the mobile-layout overflow guard that caught the compare-button regression during development. Screenshots and remaining limitations are recorded in [docs/validation.md](docs/validation.md). Rerun the commands above for results on your checkout.

Optional registry and evaluation commands:

```bash
# Re-extract the settlement registry from an Overpass osm.json, or import one:
.venv/bin/python -m pipeline.ingest.settlements data/raw/turkana-real/osm.json \
    --output data/raw/turkana-real/settlements.geojson
.venv/bin/python -m pipeline.ingest.settlements registry.csv --output registry.geojson --source-name "Name of registry"

# Registry recall, top-candidate representation and withheld-settlement recovery:
.venv/bin/python -m pipeline.evaluate --package data/processed/real.json --withhold 20
```

From the task panel use **Export JSON** or **CSV**. API exports are available as [CSV](http://127.0.0.1:8000/api/verification-tasks/export?format=csv), [JSON](http://127.0.0.1:8000/api/verification-tasks/export?format=json), or [GeoJSON](http://127.0.0.1:8000/api/verification-tasks/export?format=geojson). Local records default to `data/verification.sqlite3` and are excluded from source control.

## Repository and limits

| Path | Responsibility |
| --- | --- |
| `apps/web` | React, TypeScript, Vite and MapLibre discovery interface |
| `services/api` | FastAPI, cached routing, outreach optimisation, SQLite workflow |
| `pipeline` | Public-source adapters, projected aggregation, DBSCAN, growth and Isolation Forest |
| `data/processed` | Separate compact processed packages and machine-readable manifests |
| `tests` | Python scientific and API invariants |
| `docs` | [Architecture](docs/architecture.md), [methodology](docs/methodology.md), [demo script](docs/demo-script.md) |

This is a CPU-only laptop proof of concept. Terrain, weather, safety, road passability, transport modes and actual clinical services have not been evaluated. No field validation or model accuracy evaluation has been performed. The map uses settlement aggregates, and the application collects no personal medical information. Dataset vintage is historical; nothing is presented as a live 2026 satellite detection. Population and accessibility are estimates, and building presence cannot establish occupancy.
