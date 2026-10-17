import { number, minutes } from "./api";
import type { Settlement } from "../types";

const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

const fmt = (v: number | null | undefined, suffix = "") =>
  v == null ? "Unknown" : `${number(v)}${suffix}`;

// A one-page, print-styled brief for a local verification partner. Everything
// rendered comes from the settlement evidence snapshot — nothing invented.
export function openBrief(
  s: Settlement,
  opts: { regionName?: string; country?: string; synthetic?: boolean } = {},
) {
  const gap = s.candidate_gap_type?.replaceAll("_", " ");
  const flags = (s.data_quality_flags ?? []).map((f) => f.replaceAll("_", " "));
  const series = Object.entries(s.building_count_by_year ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const overlay = s.facility_confirmation_overlay;
  const rows: [string, string][] = [
    ["Settlement ID", esc(s.id)],
    ["Candidate gap category", gap ? esc(gap) : "Not classified"],
    ["Registry representation", esc(s.record_match_status ?? "unknown") +
      (s.nearest_registry_name ? ` · nearest record ${esc(s.nearest_registry_name)} · ${fmt(s.nearest_registry_distance_m, " m")}` : "")],
    ["Estimated population", `${fmt(s.effective_population_estimate ?? s.population_estimate)} (WorldPop-modelled reference year ${esc(s.population_reference_year ?? "?")}; not a census)`],
    ["Walk to mapped facility", `${minutes(s.walking_time_minutes)} to ${esc(s.nearest_mapped_facility_name ?? "unknown facility")}` +
      (overlay?.walking_time_minutes_after_confirmation != null
        ? ` · after a locally confirmed facility: ${minutes(overlay.walking_time_minutes_after_confirmation)}` : "")],
    ["Building signal (satellite model, not occupancy)",
      series.map(([y, v]) => `${y}: ${v == null ? "unknown" : number(v)}`).join(" · ")],
    ["Review label", s.review_label ? esc(s.review_label.replaceAll("_", " ")) : "Not yet reviewed by a local reviewer"],
    ["Key caveats", flags.length ? esc(flags.slice(0, 4).join(" · ")) : "See package manifest"],
  ];
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Investigation brief — ${esc(s.display_name)}</title>
<style>
  @page { margin: 18mm; }
  body { font: 12px/1.5 "Helvetica Neue", Arial, sans-serif; color: #111; margin: 0; }
  header { border-bottom: 2px solid #111; padding-bottom: 10px; margin-bottom: 14px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  header p { margin: 0; color: #555; font-size: 11px; }
  table { width: 100%; border-collapse: collapse; }
  td { border-bottom: 1px solid #ddd; padding: 7px 6px; vertical-align: top; }
  td:first-child { width: 34%; font-weight: 700; font-size: 10.5px; text-transform: uppercase; letter-spacing: .4px; color: #444; }
  .note { background: #f6f2e8; border: 1px solid #e3d9c2; border-radius: 4px; padding: 10px 12px; font-size: 11px; margin: 12px 0; }
  .task { border-left: 4px solid #b26a3c; padding: 8px 12px; background: #faf6f0; margin: 12px 0; }
  footer { margin-top: 16px; font-size: 10px; color: #666; border-top: 1px solid #ccc; padding-top: 8px; }
  @media print { .no-print { display: none; } }
</style></head><body>
<header>
  <h1>Investigation brief — ${esc(s.display_name)}</h1>
  <p>${esc(s.centroid[1].toFixed(4))}°N, ${esc(s.centroid[0].toFixed(4))}°E · ${esc(opts.regionName ?? "")} ${esc(opts.country ?? "")} · generated ${esc(new Date().toLocaleDateString("en-GB"))}</p>
</header>
<table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
<div class="task"><strong>Suggested next verification task</strong><div>
${esc(s.candidate_gap_type === "combined_gap"
    ? "One joint visit: confirm occupancy, record how residents reach care, and check the nearest recorded facility's services and operating status."
    : s.candidate_gap_type === "mapping_gap"
      ? "Confirm with local partners whether this settlement is known, occupied, and how it is recorded in the local registry."
      : s.candidate_gap_type === "access_gap"
        ? "Verify the mapped facility's operating status and services; ask residents how they actually reach care."
        : "Confirm the settlement remains represented in the registry and re-check after any nearby facility changes.")}</div></div>
<div class="note">${esc(synthetic_flag(opts.synthetic))}</div>
<footer>Generated from precomputed evidence; walking times are modelled estimates for representative points at 4.2 km/h. This brief does not establish occupancy, unmet need or a right to services. Verify locally before any planning decision.</footer>
<button class="no-print" style="margin-top:12px;padding:8px 14px" onclick="window.print()">Print or save as PDF</button>
<script>window.focus();</script>
</body></html>`;
  const w = window.open("", "_blank", "width=820,height=980");
  if (!w) return false;
  w.document.open();
  w.document.write(html);
  w.document.close();
  return true;
}

function synthetic_flag(synthetic?: boolean) {
  return synthetic
    ? "SYNTHETIC DEMONSTRATION RECORD: every measurement here is invented fixture data for exercising the workflow. It is not evidence about any real place."
    : "Source-derived estimates from satellite model outputs, a modelled population raster and volunteer mapping. The registry's completeness is unverified; unmatched does not mean unknown.";
}
