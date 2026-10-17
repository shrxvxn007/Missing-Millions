import { useState } from "react";
import {
  Satellite,
  Combine,
  Route,
  GitBranch,
  SlidersHorizontal,
  ExternalLink,
  Info,
} from "lucide-react";
import type { Settlement, Layers } from "../types";
import { number } from "../lib/api";
const stages = [
  {
    name: "Satellite ML",
    icon: Satellite,
    text: "Google’s satellite-trained model estimates building presence and fractional counts. Native 0.5 metre fractional-count values are summed into 250 metre analysis cells. This preview shows the aggregated count grid in its geographic position, not native imagery or individual building outlines.",
  },
  {
    name: "Settlement clustering",
    icon: Combine,
    text: "DBSCAN groups building-dense 250 metre analysis cells in a projected coordinate system. Small isolated signals are filtered. Candidates do not establish occupancy.",
  },
  {
    name: "Population + access",
    icon: Route,
    text: "Count-based population estimates are assigned once to non-overlapping candidate areas. A walking graph connects candidates to mapped facilities, including off-network distances. Missing source data stays unknown.",
  },
  {
    name: "Anomaly detection",
    icon: GitBranch,
    text: "Isolation Forest finds unusual regional feature combinations after missing-value handling and robust scaling. Five random seeds measure ranking stability, not predictive confidence. Fewer than 30 candidates disables this model.",
  },
  {
    name: "Investigation priority",
    icon: SlidersHorizontal,
    text: "A transparent regional score weights access 35%, population 25%, growth 15%, mapping discrepancy 15% and anomaly 10%. Unknown access disables the overall score. Other missing inputs contribute no points under the original weights; the result is provisional.",
  },
];
export default function Methodology({
  s,
  layers,
  synthetic,
}: {
  s: Settlement | null;
  layers: Layers;
  synthetic: boolean;
}) {
  const [active, setActive] = useState(0),
    stage = stages[active];
  const stageText =
    active === 0 && synthetic
      ? "This fixture supplies simulated annual count grids in the shape expected by the satellite-data adapter. No satellite imagery or Google model outputs are used in this mode. The local clustering and anomaly algorithms run on these simulated inputs."
      : stage.text;
  return (
    <>
      <div className="modal-kicker">UNDER THE SURFACE</div>
      <h2>How the intelligence works.</h2>
      <p className="modal-lead">
        Five inspectable steps.{" "}
        {synthetic
          ? "Working algorithms with clearly simulated inputs."
          : "Evidence for better questions."}
      </p>
      <div className="method-stages">
        {stages.map((v, i) => (
          <button
            key={v.name}
            className={active === i ? "active" : ""}
            onClick={() => setActive(i)}
          >
            <v.icon size={20} />
            <span>0{i + 1}</span>
            <strong>{v.name}</strong>
          </button>
        ))}
      </div>
      <div className="method-detail">
        <div className="eyebrow">STAGE 0{active + 1}</div>
        <h3>{stage.name}</h3>
        <p>{stageText}</p>
        <div className="intermediate">
          <span>
            PIPELINE OUTPUT{" "}
            {synthetic ? "· SYNTHETIC INPUTS" : "· REAL SOURCE INPUTS"}
          </span>
          {active === 0 ? (
            <>
              <strong>
                {number(layers.cells.features.length)} cluster-supported count
                cells
              </strong>
              <SpatialPreview layers={layers} stage={0} />
              <small>
                Each square is an analysis cell, not a building footprint. Count
                intensity reflects the latest available year.
              </small>
            </>
          ) : active === 1 ? (
            <>
              <strong>
                {number(layers.settlements.features.length)} DBSCAN candidate
                regions
              </strong>
              <SpatialPreview layers={layers} stage={1} />
              <code>
                {s
                  ? JSON.stringify(
                      {
                        candidate: s.id,
                        geometry: s.geometry.type,
                        centroid: s.centroid,
                      },
                      null,
                      2,
                    )
                  : "Reveal candidates to inspect a region."}
              </code>
            </>
          ) : active === 2 ? (
            <>
              <strong>
                {number(layers.facilities.features.length)} facility records ·{" "}
                {number(layers.roads.features.length)} road segments
              </strong>
              <SpatialPreview layers={layers} stage={2} />
              <code>
                {s
                  ? JSON.stringify(
                      {
                        routing_status: s.routing_status,
                        walk_minutes: s.walking_time_minutes,
                        snap_metres: s.road_snap_distance,
                        population: s.population_estimate,
                        population_reference_year: s.population_reference_year,
                      },
                      null,
                      2,
                    )
                  : "Select a candidate to inspect population and access. Unknown inputs appear as null."}
              </code>
            </>
          ) : active === 3 ? (
            <>
              <strong>
                {s?.anomaly_score == null
                  ? (s?.anomaly_status ??
                    "Select a candidate to inspect anomaly analysis")
                  : `Regional anomaly percentile: ${number(s.anomaly_score, 1)} / 100`}
              </strong>
              <p>
                Feature values below are comparisons with regional medians, not
                causal explanations of the forest score. Rank agreement across
                seeds is not predictive confidence.
              </p>
              <code>
                {JSON.stringify(s?.anomaly_contributors ?? [], null, 2)}
              </code>
            </>
          ) : (
            <>
              <strong>
                {s?.priority_score == null
                  ? "Priority unavailable"
                  : `Selected priority: ${number(s.priority_score)} / 100`}
              </strong>
              <code>
                {JSON.stringify(s?.priority_components ?? {}, null, 2)}
              </code>
            </>
          )}
        </div>
      </div>
      <div className="modal-disclaimer">
        <Info size={17} />
        <span>
          {synthetic
            ? "This mode uses synthetic counts, population, facilities and roads. It demonstrates algorithms, with no findings about real communities."
            : "Building presence does not prove occupancy. Mapped facilities may be incomplete. All findings require local investigation."}
        </span>
      </div>
      <a
        className="text-link"
        target="_blank"
        rel="noreferrer"
        href="https://sites.research.google/gr/open-buildings/temporal"
      >
        Open Buildings source documentation <ExternalLink size={13} />
      </a>
    </>
  );
}

function SpatialPreview({ layers, stage }: { layers: Layers; stage: number }) {
  const coords = (value: any): number[][] => {
    if (!Array.isArray(value)) return [];
    if (typeof value[0] === "number") return [value];
    return value.flatMap(coords);
  };
  const points = layers.cells.features.flatMap((f) =>
    coords(f.geometry?.coordinates),
  );
  if (!points.length) return <p>No supported spatial cells available.</p>;
  const xs = points.map((p) => p[0]),
    ys = points.map((p) => p[1]),
    west = Math.min(...xs),
    east = Math.max(...xs),
    south = Math.min(...ys),
    north = Math.max(...ys);
  const position = (p: number[]) => [
    14 + ((p[0] - west) / (east - west || 1)) * 512,
    206 - ((p[1] - south) / (north - south || 1)) * 192,
  ];
  const path = (geometry: any): string => {
    if (!geometry) return "";
    if (geometry.type === "MultiPolygon")
      return geometry.coordinates
        .map((poly: any) => path({ type: "Polygon", coordinates: poly }))
        .join(" ");
    if (geometry.type === "Polygon")
      return geometry.coordinates
        .map(
          (ring: number[][]) =>
            ring
              .map((p, i) => `${i ? "L" : "M"}${position(p).join(",")}`)
              .join(" ") + "Z",
        )
        .join(" ");
    return coords(geometry.coordinates)
      .map((p, i) => `${i ? "L" : "M"}${position(p).join(",")}`)
      .join(" ");
  };
  const count = (f: any) => {
    const series = f.properties?.building_count_by_year ?? {};
    const years = Object.keys(series).sort();
    return Number(series[years[years.length - 1]] ?? 0);
  };
  const max = Math.max(...layers.cells.features.map(count), 1);
  return (
    <svg
      className="spatial-preview"
      viewBox="0 0 540 220"
      role="img"
      aria-label={
        stage === 0
          ? "Spatial building-count analysis grid"
          : stage === 1
            ? "DBSCAN cluster boundaries over building-count cells"
            : "Road segments and mapped facilities within the analysis area"
      }
    >
      <defs>
        <clipPath id="preview-clip">
          <rect x="5" y="5" width="530" height="210" />
        </clipPath>
      </defs>
      <g clipPath="url(#preview-clip)">
        {layers.cells.features.map((f, i) => (
          <path
            key={`c${i}`}
            d={path(f.geometry)}
            fill="#bacb9d"
            fillOpacity={stage === 0 ? 0.1 + (count(f) / max) * 0.75 : 0.08}
            stroke="#b9caa1"
            strokeOpacity=".14"
            strokeWidth=".5"
          />
        ))}
        {stage === 1 &&
          layers.settlements.features.map((f, i) => (
            <path
              key={`s${i}`}
              d={path(f.geometry)}
              fill="#d8b58b"
              fillOpacity=".1"
              stroke="#dfbd90"
              strokeWidth="1.5"
            />
          ))}
        {stage === 2 && (
          <>
            {layers.roads.features.map((f, i) => (
              <path
                key={`r${i}`}
                d={path(f.geometry)}
                stroke="#72969a"
                strokeWidth=".7"
                fill="none"
              />
            ))}
            {layers.facilities.features.map((f, i) => {
              const p = position(f.geometry.coordinates);
              return (
                <circle
                  key={`f${i}`}
                  cx={p[0]}
                  cy={p[1]}
                  r="3"
                  fill="#a2c9db"
                />
              );
            })}
          </>
        )}
      </g>
    </svg>
  );
}
