import { useEffect, useState } from "react";
import { ArrowUpRight,
  ArrowRight,
  Footprints,
  Users,
  TrendingUp,
  ScanLine,
  Info,
  ChevronRight,
  LoaderCircle,
  ClipboardPlus,
  GitBranch,
  MapPinned,
  ShieldCheck,
  Printer,
} from "lucide-react";
import type { Settlement, Simulation } from "../types";
import { api, number, minutes } from "../lib/api";
import { esriChip, loadChipTile } from "../lib/satellite";
import { openBrief } from "../lib/brief";
interface Props {
  s: Settlement;
  synthetic: boolean;
  simulation: Simulation | null;
  onSimulate: () => void;
  onTask: () => void;
  onMethod: () => void;
  busy: boolean;
  reviewBusy?: boolean;
  onReview?: (label: string, notes: string) => void;
  regionNamer?: { regionName?: string; country?: string };
}
export function GrowthChart({ s }: { s: Settlement }) {
  const series = Object.entries(
    s.building_count_by_year as Record<string, number | null>,
  ).sort(([a], [b]) => a.localeCompare(b));
  const max = Math.max(
    ...series.flatMap(([, v]) =>
      typeof v === "number" && Number.isFinite(v) ? [v] : [],
    ),
    1,
  );
  return (
    <div
      className="growth-chart"
      role="img"
      aria-label={`Historical building estimates: ${series.map(([y, v]) => `${y}: ${number(v)}`).join(", ")}`}
    >
      <div className="bar-chart">
        {series.map(([y, v], i) => {
          const available = typeof v === "number" && Number.isFinite(v);
          return (
            <div
              className="chart-column"
              key={y}
              title={`${y}: ${available ? `${number(v)} model-estimated buildings` : "estimate unavailable"}`}
            >
              <span className="bar-value">
                {!available
                  ? "N/A"
                  : i === 0 || i === series.length - 1
                    ? number(v)
                    : ""}
              </span>
              <div
                style={{
                  height: available
                    ? `${Math.max(0, (v / max) * 56)}px`
                    : "0px",
                  opacity: available ? 1 : 0,
                }}
                className={`chart-bar ${i === series.length - 1 ? "last" : ""}`}
              />
              <small>{y.slice(2)}</small>
            </div>
          );
        })}
      </div>
    </div>
  );
}
export default function Evidence({
  s,
  synthetic,
  simulation,
  onSimulate,
  onTask,
  onMethod,
  busy,
  reviewBusy,
  onReview,
  regionNamer,
}: Props) {
  const [reviewNotes, setReviewNotes] = useState("");
  const [profile, setProfile] = useState<any | null>(null);
  const [chipFailed, setChipFailed] = useState(false);
  const [chipSources, setChipSources] = useState<Record<string, string>>({});
  const chip = esriChip(s.centroid[0], s.centroid[1]);
  useEffect(() => {
    let cancelled = false;
    setProfile(null);
    setChipFailed(false);
    setChipSources({});
    api<any>(`/settlements/${s.id}/access-profile`)
      .then((data) => { if (!cancelled) setProfile(data); })
      .catch(() => { if (!cancelled) setProfile({ unavailable: true }); });
    // Cache-first tile loads: first view fetches and stores, later views (and
    // offline revisits) render from the durable cache.
    chip.tiles.forEach((tile) => {
      loadChipTile(tile.url).then(({ blobUrl }) => {
        if (!cancelled) {
          if (blobUrl) setChipSources((current) => ({ ...current, [tile.url]: blobUrl }));
          else setChipFailed(true);
        }
      });
    });
    return () => { cancelled = true; };
  }, [s.id]);
  const components = Object.entries(s.priority_components ?? {});
  const sim = simulation?.settlements.find((x) => x.id === s.id);
  const populationSource =
    s.population_estimate == null
      ? "Population estimate unavailable"
      : synthetic
        ? "Synthetic population fixture"
        : `WorldPop model estimate, ${s.population_reference_year ?? "year unknown"}`;
  const stability =
    typeof s.anomaly_stability === "number"
      ? `${number(s.anomaly_stability * 100)} / 100`
      : "Not evaluated";
  const observations = Object.entries(
    s.building_count_by_year as Record<string, number | null>,
  )
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, value]) => value)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const growthUnavailable =
    observations.length < 2
      ? "Insufficient observations"
      : observations[0] < 10
        ? "Baseline too small"
        : "Change unavailable";
  const comparisons = Array.isArray(s.anomaly_contributors)
    ? s.anomaly_contributors.slice(0, 3)
    : [];
  return (
    <div className="evidence-content" key={s.id}>
      <div className="eyebrow amber">
        <span className="tiny-dot" /> INVESTIGATION CANDIDATE
      </div>
      <div className="evidence-heading">
        <h2>{s.display_name}</h2>
        <span
          className="priority-badge"
          title={`Percentile-weighted planning score (${s.priority_status?.replaceAll("_", " ") ?? "status unknown"}). Components are regional ranks under stated weights; not a medical-need probability.`}
        >
          {number(s.priority_score)}
          {s.priority_score != null && <small>/100</small>}
        </span>
      </div>
      <div className="coords">
        {s.centroid[1].toFixed(4)}° N, {s.centroid[0].toFixed(4)}° E{" "}
        <span>· {s.id}</span>
      </div>
      {s.priority_status === "provisional" && (
        <div className="provisional-label">
          PROVISIONAL SCORE · {number((s.priority_weight_coverage ?? 0) * 100)}%
          of weighted inputs available
        </div>
      )}
      {s.candidate_gap_type && s.candidate_gap_type !== "none" && (
        <div className="gap-badges">
          <span
            className={`gap-badge gap-${s.candidate_gap_type}`}
            title="Descriptive category linking this candidate's registry representation and modelled travel time. It structures investigation; it is not proven deprivation."
          >
            {s.candidate_gap_type.replaceAll("_", " ")}
          </span>
          {s.record_match_status && (
            <span
              className={`match-badge match-${s.record_match_status}`}
              title={`Representation in the selected settlement registry, which itself is unverified and possibly incomplete. ${s.nearest_registry_name ? `Nearest record: ${s.nearest_registry_name} (${number(s.nearest_registry_distance_m)} m).` : ""}`}
            >
              registry {s.record_match_status}
            </span>
          )}
        </div>
      )}
      <p className="evidence-intro">
        {s.explanation ||
          "A settlement-scale geographic hypothesis for human investigation."}
      </p>
      <div className="metric-grid">
        <div
          title={`${s.synthetic ? "Invented fixture input" : (s.source_metadata?.population_source || "Modelled population raster")} · reference year ${s.population_reference_year ?? "unknown"} · modelled distribution, not a census`}
        >
          <Users size={15} />
          <strong>{number(s.population_estimate)}</strong>
          <span>Estimated population</span>
          <small>{populationSource}</small>
        </div>
        <div
          title={`Network shortest path over the mapped walking graph at 4.2 km/h baseline. Origin: ${s.accessibility_measurement?.origin ?? "candidate representative point"}. Not every resident's journey.`}
        >
          <Footprints size={15} />
          <strong>{minutes(s.walking_time_minutes)}</strong>
          <span>To mapped healthcare</span>
          <small>
            {s.routing_status === "routable"
              ? "Available walking network"
              : s.routing_status?.replaceAll("_", " ")}
          </small>
        </div>
      </div>
      {profile && !profile.unavailable && profile.cells_measured > 0 && (
        <div className="access-profile">
          <div className="section-title">
            <span>
              <ScanLine size={14} /> Access across this settlement
            </span>
            <span className="growth-tag">{profile.cells_unknown ? `${profile.cells_unknown} cell${profile.cells_unknown === 1 ? "" : "s"} unknown` : ""}</span>
          </div>
          <div className="profile-stats">
            <div>
              <strong>{minutes(profile.median_minutes)}</strong>
              <small>median resident journey</small>
            </div>
            <div>
              <strong>{minutes(profile.p90_minutes)}</strong>
              <small>worst-tenth journey</small>
            </div>
            <div>
              <strong>{minutes(profile.walking_time_minutes_centroid)}</strong>
              <small>centroid estimate</small>
            </div>
          </div>
          {profile.median_minutes != null && profile.walking_time_minutes_centroid != null && profile.p90_minutes > profile.walking_time_minutes_centroid && (
            <p className="chart-note">
              The centroid understates how far into this settlement some residents sit by{" "}
              {number(profile.p90_minutes - profile.walking_time_minutes_centroid, 0)} minutes at the worst tenth.
            </p>
          )}
        </div>
      )}
      <div className="evidence-section">
        <div className="section-title">
          <span>
            <TrendingUp size={14} /> A changing settlement signal
          </span>
          <span className="growth-tag">
            {s.building_growth_percentage == null
              ? growthUnavailable
              : `${s.building_growth_percentage >= 0 ? "+" : ""}${number(s.building_growth_percentage)}%`}
          </span>
        </div>
        <GrowthChart s={s} />
        <div className="chart-note">
          Model-estimated buildings ·{" "}
          {synthetic ? "synthetic observations" : "satellite-derived estimates"}
          {observations.length === 2 ? " · endpoint estimates only" : ""}
        </div>
      </div>
      {s.facility_confirmation_overlay?.walking_time_minutes_after_confirmation
        != null && (
        <div className="confirmation-card simulation-impact">
          <span>RECOMPUTED AFTER A CONFIRMED FACILITY</span>
          <div>
            <strong>
              {minutes(
                s.facility_confirmation_overlay
                  .walking_time_minutes_before_confirmation,
              )}
            </strong>
            <ArrowRight size={17} />
            <strong>
              {minutes(
                s.facility_confirmation_overlay
                  .walking_time_minutes_after_confirmation,
              )}
            </strong>
          </div>
          <small>
            {s.facility_confirmation_overlay.nearest_facility_is_confirmed
              ? "Nearest recorded facility is the locally confirmed record"
              : "Nearest recorded facility unchanged"}{" "}
            · original source evidence retained
          </small>
        </div>
      )}
      <div className="facility-detail">
        <div className="facility-icon">+</div>
        <div>
          <span>Nearest mapped healthcare facility</span>
          <strong>
            {s.nearest_mapped_facility_name ??
              "Unknown — insufficient network data"}
          </strong>
          <small>
            {s.walking_route_distance_m == null
              ? "Route not established"
              : `${number(s.walking_route_distance_m / 1000, 1)} km route · ${number(s.road_snap_distance)} m off-network connection`}
          </small>
        </div>
      </div>
      {s.nearest_registry_name && (
        <div className="registry-detail">
          <div className="facility-icon">◎</div>
          <div>
            <span>Nearest recorded settlement (registry)</span>
            <strong>
              {s.nearest_registry_name}
              {s.nearest_registry_place ? ` · ${s.nearest_registry_place}` : ""}
            </strong>
            <small>
              {s.nearest_registry_distance_m == null
                ? "Registry distance unavailable"
                : `${number(s.nearest_registry_distance_m)} m from the registry point · the registry itself is unverified and may be incomplete`}
            </small>
          </div>
        </div>
      )}
      {sim && (
        <div className="simulation-impact">
          <span>HYPOTHETICAL OUTREACH SCENARIO</span>
          <div>
            <strong>{minutes(sim.before_minutes)}</strong>
            <ArrowRight size={17} />
            <strong>{minutes(sim.after_minutes)}</strong>
          </div>
          <small>Estimated walk for this candidate</small>
        </div>
      )}
      <div className="evidence-section priority-breakdown">
        <div className="section-title">
          <span>
            <ScanLine size={14} /> Why investigate here?
          </span>
          <button onClick={onMethod} title="Explain priority score">
            <Info size={14} />
          </button>
        </div>
        {components.map(([key, v]: [string, any]) => {
          const candidate =
            typeof v === "number"
              ? v
              : (v?.normalized ?? v?.normalised ?? v?.score ?? v?.value);
          const val =
            typeof candidate === "number" && Number.isFinite(candidate)
              ? candidate
              : null;
          const weight = typeof v === "object" ? (v?.weight ?? 0) : 0;
          return (
            <div
              className="score-row"
              key={key}
              title={
                val == null
                  ? `Unknown input; ${Math.round(weight * 100)}% weight contributes no points`
                  : `Regional percentile; ${Math.round(weight * 100)}% weight`
              }
            >
              <label>{key.replaceAll("_", " ")}</label>
              <div>
                <i
                  style={{
                    width:
                      val == null
                        ? "0%"
                        : `${Math.min(100, Math.max(0, val <= 1 ? val * 100 : val))}%`,
                  }}
                />
              </div>
              <span>
                {val == null
                  ? "Unknown"
                  : weight
                    ? `${Math.round(weight * 100)}%`
                    : number(val, 1)}
              </span>
            </div>
          );
        })}
        <p>
          {s.priority_score == null
            ? "Overall priority unavailable because mapped-network access is unknown."
            : s.priority_status === "provisional"
              ? "Provisional score: missing inputs contribute no points; original weights retained."
              : "Planning score, not a probability."}
        </p>
      </div>
      <div className="sensitivity-note">
        <span>ASSUMPTION CHECK</span>
        <p>
          {s.walking_time_sensitivity?.fast_5_kmh != null &&
          s.walking_time_sensitivity?.slow_3_kmh != null
            ? `${minutes(s.walking_time_sensitivity.fast_5_kmh)}–${minutes(s.walking_time_sensitivity.slow_3_kmh)} at 5–3 km/h walking speeds.`
            : "Walking-speed sensitivity unavailable."}
        </p>
        <p>
          {s.priority_stability == null
            ? "Priority ranking sensitivity not evaluated."
            : `${s.priority_stability >= 0.95 ? "Ranking stable" : "Ranking varies"} across tested ±20% weight changes.`}
        </p>
        <small>
          Facility completeness and conditions on the ground remain unverified.
        </small>
      </div>
      <button className="anomaly-row" onClick={onMethod}>
        <GitBranch size={17} />
        <div>
          <strong>
            Isolation Forest{" "}
            <span>
              {s.anomaly_score == null
                ? "Not evaluated"
                : `${number(s.anomaly_score, 1)} / 100`}
            </span>
          </strong>
          <small>Rank stability: {stability} · not predictive confidence</small>
        </div>
        <ChevronRight size={15} />
      </button>
      {comparisons.length > 0 && (
        <div className="evidence-section">
          <div className="section-title">
            <span>Features that stand out</span>
          </div>
          {comparisons.map((comparison: any) => (
            <p className="chart-note" key={comparison.feature}>
              {comparison.label}: {number(comparison.value, 1)} ·{" "}
              {comparison.direction}
            </p>
          ))}
          <p className="chart-note">
            Comparisons with regional medians, not causal explanations of the
            forest score.
          </p>
        </div>
      )}
      {onReview && (
        <div className="evidence-section review-box">
          <div className="section-title">
            <span>
              <ShieldCheck size={14} /> Local review changes the result
            </span>
            {s.review_label && (
              <span className={`match-badge match-${s.review_label === "non_residential" ? "unmatched" : "matched"}`}>
                current: {s.review_label.replaceAll("_", " ")}
              </span>
            )}
          </div>
          {s.adjustment_reason && (
            <p className="chart-note">{s.adjustment_reason}</p>
          )}
          {s.adjusted_priority?.priority_score != null && (
            <p className="chart-note">
              <b>{number(s.priority_score)}</b> before local review →{" "}
              <b>{number(s.adjusted_priority.priority_score)}</b>
              {" "}
              after applying the review over the whole region.
            </p>
          )}
          <div
            className="imagery-chip"
            title={`Satellite imagery around this candidate (${chip.zoom}z, © Esri, Maxar, Earthstar Geographics). Imagery cannot confirm occupancy or actual care access.`}
          >
            <div className="chip-frame" style={{ width: chip.size, height: chip.size }}>
              <div style={{ transform: `translate(${chip.left}px, ${chip.top}px)` }}>
                {chip.tiles.map((tile) => (
                  <img
                    key={`${tile.x}-${tile.y}`}
                    src={chipSources[tile.url] ?? ""}
                    alt=""
                    style={{
                      position: "absolute",
                      width: chip.size,
                      height: chip.size,
                      background: "#0d161a",
                    }}
                  />
                ))}
                <i className="chip-pulse" />
              </div>
            </div>
            {chipFailed && (
              <small className="chip-fallback">
                Imagery unavailable offline — review from field notes or the map.
              </small>
            )}
            <small className="chip-attrib">© Esri · Maxar · Earthstar Geographics</small>
          </div>
          <label className="field-label">
            Review note
            <textarea
              rows={2}
              value={reviewNotes}
              onChange={(e) => setReviewNotes(e.target.value)}
              placeholder="Imagery or local-contact observations …"
            />
          </label>
          <div className="review-buttons">
            {[
              ["residential", "Likely residential"],
              ["non_residential", "Not a settlement"],
              ["uncertain", "Uncertain"],
            ].map(([value, label]) => (
              <button
                key={value}
                disabled={reviewBusy}
                className={
                  s.review_label === value
                    ? "review-button active"
                    : "review-button"
                }
                title={
                  value === "non_residential"
                    ? "Removes this candidate's population weight and recomputes regional priorities"
                    : value === "residential"
                      ? "Strengthens investigation value for this candidate"
                      : "Keeps the ranking and raises review priority"
                }
                onClick={() => onReview(value, reviewNotes)}
              >
                {reviewBusy ? (
                  <LoaderCircle className="spin" size={13} />
                ) : (
                  <MapPinned size={13} />
                )}{" "}
                {label}
              </button>
            ))}
          </div>
          <small className="chart-note">
            Labels adjust the ranking with a visible reason; they cannot confirm
            occupancy or actual access by themselves.
          </small>
        </div>
      )}
      <div className="uncertainty">
        <Info size={14} />
        <p>
          {synthetic
            ? "Synthetic demonstration data. These are simulated communities and measurements, not findings about people in Uganda."
            : s.data_quality_flags
                ?.slice(0, 2)
                .map((flag: string) => flag.replaceAll("_", " "))
                .join(" · ") ||
              "Historical satellite estimates. Facility completeness unverified. Field validation required."}
        </p>
      </div>
      <button
        className="primary-button full"
        onClick={onSimulate}
        disabled={busy}
      >
        {busy ? (
          <LoaderCircle className="spin" size={17} />
        ) : (
          <ArrowUpRight size={17} />
        )}{" "}
        What if care went to them?
      </button>
      <button className="secondary-button full" onClick={onTask}>
        <ClipboardPlus size={15} /> Create investigation task
      </button>
      <button
        className="secondary-button full"
        onClick={() =>
          openBrief(s, {
            regionName: regionNamer?.regionName,
            country: regionNamer?.country,
            synthetic,
          })
        }
        title="A one-page evidence brief for local verification partners"
      >
        <Printer size={15} /> Print investigation brief
      </button>
    </div>
  );
}
