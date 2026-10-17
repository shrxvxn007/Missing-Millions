# Methodology and interpretation

The output is a geographic hypothesis for human investigation. It is not a diagnosis, a claim that a community is unserved, or a probability of medical need.

## Sources and quantities

Google Open Buildings 2.5D Temporal supplies satellite-model predictions of building presence, fractional building count and height for 2016–2023. Google describes an effective resolution of about 4 m while distributing native 0.5 m rasters. Building presence scores are uncalibrated. Our acquisition route reads native `building_fractional_count` band values and sums their contributions, without thresholding pixels into individual buildings. The `building_presence` band is summarized separately. See the [dataset catalog](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1), [producer FAQ](https://sites.research.google/gr/open-buildings/temporal/) and [official acquisition notebook](https://github.com/google-research/google-research/blob/master/building_detection/open_buildings_temporal_download_region_geotiffs.ipynb).

The local source sample acquires the 2016 and 2023 endpoints only. Intermediate years remain absent. No interpolated observation is displayed as source evidence. A separate synthetic fixture includes invented annual values and carries its synthetic label at source, package and interface levels.

WorldPop Global2 uses modelled population counts. The Uganda 2023 constrained 100 m R2025A v1 item explicitly specifies people per pixel, despite one asset description using the word “density.” Source metadata, reference year and release are preserved in `worldpop-item.json`; see the [official STAC item](https://api.stac.worldpop.org/collections/UGA/items/uga_pop_2023_CN_100m_R2025A_v1). A native pixel contributes its count once to the analysis cell containing its projected centroid. Counts are summed, never averaged. At polygon boundaries this centroid assignment is an approximation at the source resolution. People are never estimated by an assumed residents-per-building multiplier.

OSM provides mapped walking ways and general healthcare objects, using hospital, clinic, doctor and health-post categories. Pharmacies and dentists are excluded by default. The acquisition includes a 20 km surrounding buffer, preserving way node IDs so intersections share graph vertices. An object appearing under multiple tags is retrieved once by its OSM identity; preprocessing reconciles nearby duplicate facility representations. Source IDs remain available. OSM completeness and clinical service availability have not been evaluated. See [Overpass documentation](https://wiki.openstreetmap.org/wiki/Overpass_API).

## Count-preserving grid and clustering

The compact source grid covers 5 km × 5 km in EPSG:32636, with 20 × 20 non-overlapping 250 m cells. Native 0.5 m fractional contributions are read from COG windows without selecting coarse overviews. At an overlapping tile edge, each native pixel is used once. A cell lacking complete native coverage remains unavailable rather than becoming zero. Direct fractional-count summation applies to these native distributed rasters; arbitrary resampled rasters require explicit unit and resolution treatment.

The generic local raster adapter supports count-aware aggregation onto a common metric grid. Bilinear interpolation and a simple mean of count-valued rasters are inappropriate substitutes. Available population pixels are assigned once, and overlapping input candidate areas are resolved deterministically in stable-ID order.

DBSCAN groups latest-year cell centres with at least eight model-estimated buildings per cell. Default `eps=360 m`, `min_samples=2`, and a minimum cluster total of 30 buildings suppress small isolated signals. Candidate boundaries are unions of analysis cells. These are settlement-scale regions, not recovered building outlines. Candidate IDs hash projected grid location and cell membership. A source or threshold change can change membership and consequently the ID.

Annual building totals use the same candidate cells in every available year, enabling a consistent spatial comparison. The method is conditioned on the latest-year occupied-looking cells; it does not claim to detect every historical settlement or demolition site.

## Temporal analysis

For first and last available years, absolute change is `last − first`; percentage change is `100 × change / first` only when the initial estimate is at least ten. Otherwise relative growth is unknown. Annual change uses a Theil–Sen slope across actual observations. A persistence indicator needs at least three years and allows a small model-noise tolerance. Two endpoint observations cannot establish persistent growth. Temporal misalignment, imagery quality and classification changes may explain part of any difference.

## Walking accessibility

The graph uses mapped way vertices and consecutive edges with projected lengths. The default OSM walking import excludes motorway, construction/proposed ways, `foot=no`, private access and area features. The small adapter treats permitted walking ways as undirected; special pedestrian one-way restrictions, turn rules and conditional access need a richer import for operational use.

Both candidate and facility connect to a nearest network node. Connection distance is included in the route, using a baseline 4.2 km/h walking assumption. Connections over 1,500 m are insufficient-network results. A virtual source initialized with facility connection distances supports shortest routes **to** mapped facilities. Directed graph inputs are reversed correctly for this computation.

An unreachable graph component is unknown access, never proof that no path exists. A candidate's representative point is only one proxy for a potentially large region. The real sample includes a 317-cell urban region, so the reported walk cannot describe every resident's journey or within-region inequality. Sensitivity outputs recalculate the same route distance at 3, 4.2 and 5 km/h. Under 30, 30–60, 60–120 and over 120 minute bands are configurable planning categories, not clinical standards. Terrain, seasonal access, safety, public transport, opening hours, waiting time and service capacity are not modelled.

## Anomaly detection and investigation ranking

Isolation Forest runs only with at least 30 candidates. Available predictors include population, building density, absolute and relative growth, walking time, road density, network connection distance and OSM building discrepancy. Appropriate log/signed-log transforms, median imputation, explicit missing flags and robust IQR scaling handle feature distributions. A wholly unavailable predictor is removed from the numerical matrix. The real source sample currently leaves OSM building discrepancy unknown because no building-footprint comparison was acquired.

Five reproducible seeds (11, 29, 47, 71, 101), each with 128 trees, produce regional anomaly percentile ranks. Their mean is the displayed anomaly score. Rank variation across seeds provides a stability indicator; it is not calibrated confidence. Feature explanations report deviations from regional medians, not causal attributions or per-tree explanations. A small real region can produce only one continuous settlement candidate; the anomaly model then explicitly disables itself instead of inventing a result.

The priority score combines empirical regional percentile ranks with access 35%, population 25%, positive absolute growth 15%, mapping discrepancy 15%, and anomaly 10%. Weights are product assumptions. Equal values share rank. Unknown access disables the overall score. Other absent components contribute no points while retaining original weights; the incomplete score is labelled provisional and its weight coverage is reported. Missing evidence never raises priority through weight renormalization. Rankings are relative to the analyzed region and are not comparable probabilities across regions.

Weight sensitivity perturbs each weight ±20% and renormalizes the scenario weights, reporting score/rank variation. Walking-speed sensitivity is also available. Population-error scenarios and repeated clustering-threshold sensitivity are not currently implemented; no general confidence interval or external accuracy claim is made.

## Hypothetical outreach

Greedy maximum coverage chooses road-node locations that add the greatest target population within a selected walking threshold, accounting for baseline facility coverage and settlement connectors. Distances and selected locations are computed from the active graph. Unknown population receives no numerical weight. A candidate's entire aggregate population is represented at its centroid, an approximation that should not be read as household coverage.

The displayed coverage geometry consists of reachable road segments, clipped to the distance threshold. It is not a terrain-aware isochrone polygon. Proposed stops have no verified operational feasibility. Community participation, road usability, safe stopping space, staffing, facility capacity and permissions require human assessment.

## Validation boundary

Automated tests check numerical/geospatial invariants, deterministic ML behavior, missing-data handling, shortest paths, hypothetical coverage, API validation and local task persistence. These are implementation checks. No field validation, settlement occupancy validation, clinical outcome evaluation or region-specific predictive accuracy study has been performed. Consult the acquisition report and source manifest for exactly which inputs were actually obtained.
