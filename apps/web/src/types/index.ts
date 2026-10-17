export type FeatureCollection = { type: "FeatureCollection"; features: any[] };
export interface Region {
  id: string;
  name: string;
  country: string;
  bbox: number[];
  center: [number, number];
  data_mode: string;
  years: number[];
  [key: string]: any;
}
export interface Settlement {
  id: string;
  region_id: string;
  display_name: string;
  geometry: any;
  centroid: [number, number];
  building_count_by_year: Record<string, number | null>;
  building_count_change: number | null;
  building_growth_percentage: number | null;
  population_estimate: number | null;
  population_reference_year: number | null;
  osm_building_discrepancy: number | null;
  road_density: number | null;
  road_snap_distance: number | null;
  nearest_mapped_facility_id: string | null;
  nearest_mapped_facility_name: string | null;
  nearest_mapped_facility_distance_m: number | null;
  walking_route_distance_m: number | null;
  walking_time_minutes: number | null;
  routing_status: string;
  anomaly_score: number | null;
  anomaly_stability: any;
  anomaly_contributors: any;
  priority_score: number | null;
  priority_components: any;
  priority_stability: any;
  source_metadata: any;
  data_quality_flags: string[];
  verification_status: string;
  record_match_status?: string | null;
  nearest_registry_name?: string | null;
  nearest_registry_distance_m?: number | null;
  candidate_gap_type?: string | null;
  review_label?: string | null;
  adjustment_reason?: string | null;
  adjusted_priority?: { priority_score?: number | null; [k: string]: any } | null;
  effective_population_estimate?: number | null;
  facility_confirmation_overlay?: {
    walking_time_minutes_after_confirmation?: number | null;
    walking_time_minutes_before_confirmation?: number | null;
    walking_minutes_change?: number | null;
    nearest_facility_is_confirmed?: boolean;
    [k: string]: any;
  } | null;
  classifier_residential_probability?: number | null;
  history?: { year: number; buildings: number }[];
  explanation: string;
  [key: string]: any;
}
export interface Layers {
  settlements: FeatureCollection;
  facilities: FeatureCollection;
  roads: FeatureCollection;
  cells: FeatureCollection;
  registry?: FeatureCollection;
}
export interface Simulation {
  locations: any[];
  summary: Record<string, any>;
  settlements: {
    id: string;
    before_minutes: number | null;
    after_minutes: number | null;
    newly_covered: boolean;
  }[];
  coverage_network: FeatureCollection;
  assumptions: string[];
  [key: string]: any;
}
export interface Task {
  id: string;
  settlement_id: string;
  status: string;
  notes: string;
  created_at: string;
  [key: string]: any;
}
