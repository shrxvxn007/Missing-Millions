# Data packages and acquisition

`data/processed/demo.json` is the explicit synthetic demonstration fixture. Its building counts, population, roads and facilities are invented inputs for exercising real algorithms. It is not evidence about residents, services or settlements in Kenya. `data/processed/real.json`, when prepared successfully, contains acquired-source analysis for a compact Turkana County (Kenya) sample. Real and synthetic packages are never merged or silently substituted.

`data/raw/turkana-real/acquisition-report.json` is the machine-readable inventory of acquisition success and blockers. `provenance.json` preserves source URLs, vintages, retrieval times, licenses, transformations and limitations. An acquired source file is distinct from a completed processed real package. A source report marked incomplete does not authorize presenting a synthetic fixture as real.

## Acquired source sample

All three requested source families were acquired on 17 October 2026 for the Turkana sample, together with the mapped settlement registry. The acquisition check returns `complete: true`. These are source inventory totals across the grid or buffered extract, not counts of overlooked communities or people needing healthcare:

| Source | Actual acquired quantity |
| --- | --- |
| Google temporal model outputs | 1,600 complete 250 m count/presence cells for each of 2016 and 2023; whole-grid fractional-count sums 371.40 and 860.86 (sparse rural sample) |
| WorldPop 2023 constrained Global2 | Native AOI clip; count-grid sum 768.80; 66.2 MB country raster downloaded to a temporary directory because the server lacks HTTP ranges; only the AOI clip is retained |
| OpenStreetMap | 3,312 walking ways; 2 mapped healthcare objects; graph of 57,330 vertices and 60,418 edges |
| Mapped settlement registry | 55 `place=*` records inside the analysis extent (from the 20 km buffered query), retained as the reference layer for matching — an unverified, potentially incomplete volunteer record |

OSM's base timestamp is recorded in `provenance.json`. The two Google years and WorldPop reference year are historical model estimates. Field verification has not been performed.

The prepared real package contains **two DBSCAN candidates**. One registered settlement is modelled at a **142-minute walk** to mapped care (access gap); one satellite signal cannot be confidently matched to the registry and sits at a **233-minute modelled walk** (combined-gap candidate). Both candidates are far beyond the 60-minute demonstration threshold, and each carries explicit uncertainty rather than a claim of proven deprivation. Two candidates are below the minimum sample of 30, so Isolation Forest is explicitly disabled for this real package. Priority scores are provisional because anomaly and OSM building-discrepancy components are unavailable. The labelled synthetic fixture demonstrates a larger candidate comparison with the actual local anomaly algorithm.

## Prepare sources

From the repository root, after installing dependencies:

```bash
# Inventory only: no credentials read and no network requests.
.venv/bin/python -m pipeline.ingest.acquire_sources --check

# Explicit public-source downloads; no Earth Engine credentials required.
.venv/bin/python -m pipeline.ingest.acquire_sources --sources all

# Build a distinct processed package after the required files are present.
.venv/bin/python -m pipeline.build_demo --mode real --source data/raw/turkana-real

# Choose the real package when starting the server.
DATA_PACKAGE_PATH=data/processed/real.json .venv/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

The check command exits 0 when all expected real inputs exist, or 2 for an incomplete inventory. Acquisition exits nonzero if a requested source failed; it records the reason and continues other independent sources. It never generates a fixture in response to failure. Download requests need an internet connection. Overpass public services may be slow or unavailable; its endpoint is configurable through `--overpass`. Identical cached OSM queries are reused.

The WorldPop server used for this sample does not support HTTP range requests. The adapter therefore downloaded its 66.2 MB Kenya raster into a temporary directory, kept the small source clip and removed the country file. The fallback rejects country downloads above 80 MB. Google source reads use actual native COG windows and retain only aggregated arrays plus the official manifests.

The default source AOI is a 10 km × 10 km metric grid centred on 35.72 °E, 3.18 °N in Turkana County, Kenya (rural Lodwar district, west of the A1). It uses EPSG:32636, 250 m cells. WGS84 bounding box is recorded in `grid.json`. The compact size keeps native raster requests manageable while sitting inside the roughly 30 × 30 km planning envelope; the specific boundary was chosen after confirming Open Buildings tile coverage (manifest token 17, 4 intersecting tiles). Roads, facilities and settlement-registry records include a 20 km buffer. This is a technical source sample, not a representative sample of Turkana County. The larger synthetic fixture uses the same general geographic setting for illustration only.

## Raw real-source contract

| File | Contents |
| --- | --- |
| `grid.json` | CRS, west/north origin, width/height, metric cell size and WGS84 extent |
| `buildings.npz` | `counts_2016`, `counts_2023`, native-signal `presence_YEAR` and source `coverage_YEAR`, each `(height,width)` |
| `worldpop2023.tif` | Small native count raster clip with source NoData and geographic transform |
| `population.npz` | `population` count grid assigned once by native pixel centroid |
| `worldpop-item.json` | Exact official STAC item and download URL |
| `open-buildings-manifest-YEAR.json` | Official tile definitions, band meanings and native transforms |
| `osm.json` | Cached Overpass response with OSM object IDs and node references |
| `facilities.geojson` | General healthcare source records as WGS84 points |
| `roads.geojson` | Permitted walking ways retaining original geometry and node IDs |
| `graph.json` | Undirected walking topology with metric edge lengths |
| `provenance.json` | Dataset-level provenance and processing |
| `acquisition-report.json` | Explicit acquired/not-acquired inventory |

NumPy arrays can use NaN for missing source support; the processed external JSON uses `null`. Do not fill unknown population or routes with numerical zero. No OSM building-footprint comparison is currently acquired, so that scoring feature remains unavailable rather than becoming an invented discrepancy.

## Sources and attribution

Google Research [Open Buildings 2.5D Temporal v1](https://sites.research.google/gr/open-buildings/temporal/) supplies model predictions for 2016 and 2023. The source is not a live 2026 image. The adapter follows the anonymous GCS discovery route in the [official notebook](https://github.com/google-research/google-research/blob/master/building_detection/open_buildings_temporal_download_region_geotiffs.ipynb), selects native fractional-count and presence bands, and sums native count contributions. We choose CC BY 4.0 from the producer's dual-license offer. Credit Google Research and Copernicus Sentinel-2. A COG's 0.5 m stored pixels do not establish 0.5 m model accuracy; producer effective resolution is about 4 m.

WorldPop, University of Southampton [Global2 Kenya 2023 constrained R2025A v1](https://api.stac.worldpop.org/collections/KEN/items/ken_pop_2023_CN_100m_R2025A_v1) supplies approximately 100 m modelled people-per-pixel counts, under CC BY 4.0. Preserve DOI `10.5258/SOTON/WP00839`, reference year 2023 and release R2025A v1. Counts are not a measured settlement census.

© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL 1.0, provide mapped ways and general healthcare features. Preserve attribution and source identity when distributing derived data. This implementation does not claim that missing OSM records imply missing real-world services.

For a credentialed Earth Engine workflow, register an authorized Cloud project, install/authenticate `earthengine-api`, and select `GOOGLE/Research/open-buildings-temporal/v1`. Export `building_fractional_count` and `building_presence` for the actual source years at their native grid, retaining projection, scale and count semantics; feed compatible arrays into the contract above. The bundled tested acquisition route uses public GCS directly and does not read credentials. Google’s linked count example redirects to sign-in in an unauthenticated session; do not infer a safe count scaling factor for an arbitrary Earth Engine export. Native source-window sums avoid that ambiguity here.

## Optional facility-register import

`pipeline.ingest.facilities.import_facilities(path, source_name=..., source_url=...)` accepts a CSV with `lon`, `lat`, `name`, `category` columns and optional `source_id`, `source`. It also accepts WGS84 Point GeoJSON with those properties. General healthcare categories are hospital, clinic, doctor/doctors and health_post/healthpost. Specialist or unknown categories are excluded and recorded in the import report; invalid, nonfinite or out-of-range coordinates raise an error.

`merge_facilities(osm_collection, imported_collection, projected_crs=...)` returns a new GeoJSON collection, reconciling same normalized names within 100 m while retaining all original source IDs and source records. Distinct names and anonymous facilities remain separate. Both functions preserve a file checksum, source reference, import timestamp and exclusions in GeoJSON provenance. Importing a register does not independently verify its currency, licensing or clinical capability.

```bash
.venv/bin/python -m pipeline.ingest.facilities path/to/authorized-register.csv \
  --source-name "Provided facility register" \
  --source-url "https://publisher.example/register" \
  --merge-osm data/raw/turkana-real/facilities.geojson \
  --output data/raw/facilities-reviewed-merge.geojson
```

The command writes a separate reviewable result. It does not modify the cached OSM response or activate new records automatically. After source/license review, place the merged facility collection into a separate real source pack as `facilities.geojson`, retain its provenance, and rebuild that package. No government, NGO or locally verified facility register was supplied or imported into the bundled sample.

See `docs/methodology.md` for aggregation, clustering, routing, anomaly, prioritization, sensitivity and interpretation limits. Investigation tasks are stored separately in `data/verification.sqlite3` by default and can be exported from the interface.
