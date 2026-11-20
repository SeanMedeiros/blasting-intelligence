export interface SurveySummary {
  id: number;
  code: string;
  survey_type: string;
  surveyed_at: string;
  area: string;
  bench: string | null;
  blast: string | null;
  instrument: string | null;
  operator: string | null;
  point_count: number;
  point_spacing_mm: number | null;
  registration_error_mm: number | null;
  coordinate_system: string;
  file_format: string | null;
  imported: boolean;
  quality_status: string;
  quality_notes: string | null;
}

export interface SurveyDetail extends SurveySummary {
  references: { value: string; label: string }[];
  default_reference: string;
  display_points: number;
  comparisons: { id: number; reference: string; within_tolerance_pct: number; mean_m: number; std_m: number; computed_at: string; computed_by: string | null }[];
}

export interface Stats {
  reference: string;
  count: number;
  region?: string;
  mean_m?: number;
  std_m?: number;
  p05_m?: number;
  p95_m?: number;
  max_abs_m?: number;
  within_tolerance_pct?: number;
  above_tolerance_pct?: number;
  below_tolerance_pct?: number;
  tolerance_m?: number | null;
  tolerance_source?: string;
  sign_convention?: string;
  histogram?: { edges: number[]; counts: number[] };
}

export interface CloudData {
  n: number;
  hasDev: boolean;
  xyz: Float32Array;
  intensity: Float32Array;
  dev: Float32Array;
  region: Uint8Array;
}

export interface Mesh {
  vertices: number[];
  indices: number[];
  deviation: (number | null)[];
}

export interface Hole {
  id: number;
  hole_code: string;
  row: number;
  x: number;
  y: number;
  z: number;
  depth_m: number;
  status: string;
}

export interface FrontRow {
  holes: {
    x: number;
    hole_code: string;
    valid: boolean;
    min_distance_m?: number;
    min_at_z_m?: number;
    crest_distance_m?: number | null;
    toe_distance_m?: number | null;
    flags: string[];
  }[];
  reference?: { min_distance_m: number | null; toe_distance_max_m: number | null; source: string | null; is_demo_placeholder: boolean };
  note?: string;
}

export interface Section {
  x: number;
  survey: [number, number][];
  reference: [number, number][] | null;
  reference_label: string | null;
  holes: Hole[];
}

export function parseCloud(buf: ArrayBuffer): CloudData {
  const head = new Uint32Array(buf, 0, 2);
  const n = head[0];
  let off = 8;
  const xyz = new Float32Array(buf, off, n * 3);
  off += n * 12;
  const intensity = new Float32Array(buf, off, n);
  off += n * 4;
  const dev = new Float32Array(buf, off, n);
  off += n * 4;
  const region = new Uint8Array(buf, off, n);
  return { n, hasDev: head[1] === 1, xyz, intensity, dev, region };
}
