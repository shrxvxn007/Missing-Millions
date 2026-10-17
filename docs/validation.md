# Validation record — 17 October 2026

This record describes checks actually executed against this checkout.

- **65 Python tests passed** (exit 0): the previous 62 plus 3 new tests for the tier-1/2 surface — per-cell access profiles (one measured cell + one honestly unknown cell in the fixture), regional comparison aggregates, and the live blind test (withhold 2 of 4 fixture registry records, disclosure string asserted, invalid withhold → 422).
- **TypeScript validation and Vite production build passed** (exit 0), covering the access-profile section, imagery chip, compare modal, blind-test panel, printable brief and provenance tooltips.
- **3 Playwright browser tests passed** (exit 0, 15.3 s). The mobile-layout journey caught a real regression introduced by the new Compare trigger — the header overflowed horizontally at 390 px — which was fixed with a responsive rule and verified with a DOM-level overflow probe (`scripts/probe-mobile-overflow.js`: scrollWidth 390, zero overflowing elements after the fix).
- Live API verification on the real processed packages: health lists `turkana-real` / `mbale-real` / `turkana-demo` independently; overview summaries now carry registry match statuses and in-extent recall per region.

## Pilot moved to Turkana County, Kenya (spec-aligned)

- The acquisition defaults now follow the project plan: **Turkana County, Kenya** (35.72 °E, 3.18 °N, rural Lodwar district inside the plan's ~30 × 30 km envelope) with country-generalised WorldPop handling (KEN STAC item verified) and automatic Open Buildings manifest-token discovery (token 17 confirmed to cover the AOI with 4 tiles).
- Acquired: 1,600 complete 250 m count cells per year (whole-grid fractional-count sums 371.40/860.86 — a genuinely sparse rural sample), WorldPop 2023 KEN clip (grid sum 768.80), OSM 3,312 walking ways / graph 57,330 nodes / **2 mapped facilities**, and **55 settlement-registry records** in extent.
- Two real candidates result, both honestly far beyond the 60-minute demonstration threshold: one **matched** registered settlement at a **142-minute modelled walk** (access_gap) and one signal **unmatched** in the registry at a **233-minute walk** (combined_gap). In-extent registry recall is 1.0 (2 of 2 registered points covered) — a small-sample geometric claim only.
- **Satellite basemap added**: Esri World Imagery raster tiles (© Esri, Maxar, Earthstar Geographics) rendered beneath the local evidence layers, switchable in Map layers; the interface degrades to the dark offline canvas with imagery hidden or without a network.
- The synthetic fixture is likewise re-anchored to a Turkana geographic reference (`turkana-demo`) with invention clearly labelled.

## Discovery→verification loop checks (first Mbale sample, kept as an alternate source layout)

- The Overpass acquisition now extracts a **mapped settlement registry** (`place=*`, 4,567 records in the 20 km buffer, 106 inside the 5 km AOI). Documented upstream outage fallback: registry import/merge adapters accept CSV/GeoJSON.
- Real-package candidates now carry match status and gap categories. Example produced by the data: one real candidate is **matched** to a recorded settlement; the other is **ambiguous** (≈900 m from a recorded hamlet) — classed a `mapping_gap` candidate needing local confirmation, with an explicit record that absence from the registry proves nothing.
- A synthetic package review label of `non_residential` moved that candidate's priority from **75.6 to 65.2** on a live recomputation, and the review queue reordered (top item 26.5 investigation value → excluded after review). The label classifier correctly reported `insufficient_labels` under the two-class minimum.
- Adding a confirmed clinic on the demo graph re-routed access and updated 24 regional rankings; 3 candidates reached recorded care sooner in the live check; records persist in SQLite across application restarts.
- `pipeline.evaluate` on the real package: in-extent registry recall **3.77 %** (4 of 106 in-AOI registry points covered by gated 250 m-cell detection) — reported honestly as a limitation of this compact sample rather than tuned away; top-2 registry representation 100 % (1 matched + 1 ambiguous); withheld-20 recovery 0 % with full disclosure that omissions are evaluation artifacts.
- Sparse-signal retention was exercised in unit tests; the two prepared packages contain no clusters in the 12–30 building band, so their outputs are unchanged by that policy.

## Scientific checks

The acquired source pack was checked for finite native count aggregates, source/candidate conservation bounds, unique cell assignment, no population double counting, source presence and provenance. It contains two actual satellite years, not invented intermediate observations. The real sample's two DBSCAN candidates are too few for the configured 30-candidate minimum; Isolation Forest stays disabled there. Five seeded forests run on the separate 42-candidate synthetic fixture.

The real sample supports both a zero-benefit outreach result for an already-covered representative point and a positive-benefit result for the second candidate. These are modelled planning scenarios, not demonstrated service delivery or health outcomes. All resident coverage uses settlement representative points; it does not establish each resident's individual access.

## Performance measured locally

A cold real-package health request took 0.712 seconds; region/overview requests then took about 0.001 seconds; the clipped map-layer response took 0.777 seconds and was approximately 786 KB. The first real simulation took 3.391 seconds including graph preparation; a cached simulation took 0.140 seconds. These are laptop measurements, not service-level guarantees. The full buffered graph remains a large local processing file; the browser never receives it.

## Remaining scope and limitations

The real region is a focused 5 × 5 km source sample near Mbale, rather than a validated 25 × 25 km regional study. No field validation, occupancy validation, medical-need prediction, model accuracy evaluation, government partnership, clinical capacity assessment or outreach approval has occurred. No verified external facility register was supplied; CSV/GeoJSON import adapters are available.

The interface renders local count cells, settlement boundaries, vector roads and, when online and enabled, the Esri World Imagery raster basemap. Its real timeline contains only 2016 and 2023. OSM building-discrepancy evidence is unavailable, so real priorities are provisional. Walking speed, weight perturbations and forest seeds are tested; broader population, detection-threshold and facility-category sensitivity experiments remain future work. The simple OSM walking import assumes bidirectional paths and does not fully interpret special pedestrian turn/conditional-access restrictions. Operational routing needs a richer access policy and local review.

**Performance fix verified with measurements (access profiles + chip caching):** before the change, the first evidence-panel open built the full routing graph (measured: Turkana 419 ms, Mbale 2,948 ms, engine constructed both times). After in-package precomputation of per-cell access profiles, `scripts/bench_access_profiles.py` reports **0.0 ms per call with no engine build** on turkana/mbale/demo, and the precomputed medians are identical to the previously measured live-routing values (Turkana 144.4 min, Mbale 8.7 min), so the two paths are provably consistent. A dedicated test asserts the evidence-panel profile endpoint never builds the routing engine on a prepared package. Imagery chips now store tile responses in the durable Cache API (`loadChipTile`), so revisited chips render from local storage without a network.

This is a local, CPU-only hackathon proof of concept. It has not been deployed or approved for operational planning.

The documented `make dev` command was also started successfully: Vite became ready in 174 ms, FastAPI started on port 8000, and both the frontend document and its proxied `/api/health` returned successful responses with the real and synthetic packages listed separately. Owned preview/test servers were stopped after validation. Generated browser-test records were removed from the default application database; isolated browser tests used a temporary database.
