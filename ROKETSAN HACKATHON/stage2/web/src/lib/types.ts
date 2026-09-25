// Mirrors src/sentinel/domain/models.py (JSON shapes returned by the FastAPI layer).

export type Level = "DÜŞÜK" | "ORTA" | "YÜKSEK" | "KRİTİK";
export type VerdictT = "DOĞRULANDI" | "ÇELİŞİYOR" | "DOĞRULANAMAZ" | "İLGİSİZ";
export type Label = "car" | "van" | "truck" | "bus" | "unknown";

export interface StopSegment { start: string; end: string; minutes: number }

export interface Kinematics {
  track_id: string;
  t_now: string;
  d_now_m: number;
  d_start_m: number;
  d_change_m: number;
  closing_mps: number;
  align_cos: number;
  speed_now_mps: number;
  speed_mean_mps: number;
  speed_max_mps: number;
  path_m: number;
  heading_deg: number | null;
  heading_dir: string | null;
  stops: StopSegment[];
  stop_total_min: number;
  stop_and_go: boolean;
  approaching: boolean;
  leaving: boolean;
  eta_min: number | null;
  zones_passed: string[];
  window: [string, string];
  d_series: [string, number][];
}

export interface RiskFactor {
  code: string;
  label: string;
  points: number;
  vehicle_ref: string | null;
  evidence_refs: string[];
}

export interface Vehicle {
  ref: string;
  det_id: string;
  label: Label;
  conf: number;
  bbox: [number, number, number, number];
  lat: number;
  lon: number;
  d_base_m: number;
  direction: string;
  promoted: boolean;
  track_id: string | null;
  match_m: number | null;
  margin_m: number | null;
  second_track_id: string | null;
  kinematics: Kinematics | null;
  score: number;
  factors: RiskFactor[];
}

export interface Claim {
  types: string[];
  lat: number | null;
  lon: number | null;
  zone: string | null;
  vehicle_word: string | null;
  count: number | null;
}

export interface ReportVerification {
  report_id: string;
  time: string;
  source: "official" | "third_party";
  text: string;
  claim: Claim;
  verdict: VerdictT;
  reason: string;
  relevance: string;
  evidence_refs: string[];
  related_tracks: string[];
  identity_claim: boolean;
  dist_to_frame_m: number | null;
}

export interface RiskAssessment {
  score: number;
  score_level: Level;
  floor_level: Level | null;
  floor_reasons: string[];
  level: Level;
  factors: RiskFactor[];
  top_vehicle: string | null;
}

export interface FrameInfo {
  image_id: string;
  capture_time: string;
  zone: string;
  center_lat: number;
  center_lon: number;
  d_base_m: number;
  direction: string;
  width_m: number;
  height_m: number;
  width_px: number;
  height_px: number;
  corners: {
    top_left: [number, number];
    top_right: [number, number];
    bottom_left: [number, number];
    bottom_right: [number, number];
  };
}

export interface EvidencePacket {
  image_id: string;
  frame: FrameInfo;
  detector: string;
  vehicles: Vehicle[];
  untracked: string[];
  undetected_tracks: string[];
  reports: ReportVerification[];
  risk: RiskAssessment;
  uncertainties: string[];
}

export interface KeyFinding { vehicle_ref: string | null; statement: string; evidence_refs: string[] }

export interface RiskBrief {
  image_id: string;
  risk_level: Level;
  risk_score: number;
  headline: string;
  key_findings: KeyFinding[];
  report_assessment: { report_id: string; verdict: VerdictT; reason: string }[];
  recommended_action: string;
  confidence: string;
  uncertainties: string[];
  level_rationale: string | null;
}

export interface Grounding {
  checked: number;
  failed: string[];
  unknown_refs: string[];
  level_ok: boolean;
  level_issue: string | null;
  passed: boolean;
}

export interface EvaluationResult {
  run_id: string;
  packet: EvidencePacket;
  brief: RiskBrief;
  brief_source: "llm" | "llm_cache" | "template";
  grounding: Grounding;
  llm_note: string | null;
  timings_ms: Record<string, number>;
}

export interface Decision {
  decision_id: string;
  run_id: string;
  image_id: string;
  action: "approve" | "override" | "escalate" | "undo";
  level: Level | null;
  reason: string;
  at: string;
}

export interface FrameResponse { result: EvaluationResult; decision: Decision | null }

export interface TriageRow {
  image_id: string;
  zone: string;
  capture_time: string;
  level: Level;
  score: number;
  d_base_m: number;
  headline: string;
  n_vehicles: number;
  reports_contradicted: number;
  reports_confirmed: number;
  min_eta_min: number | null;
  n_approaching: number;
  n_heavy: number;
  decision: Decision | null;
}

export interface ShiftSummary {
  frames: number;
  reports: number;
  by_level: Record<Level, number>;
  most_urgent: TriageRow | null;
  contradicted_reports: number;
  decided: number;
  awaiting_high: number;
  decision_median_s: number | null;
  decision_timed: number;
  high_decided: number;
  high_downgraded: number;
}

export interface HandoverReport {
  report_id: string;
  time: string;
  text: string;
  identity_claim: boolean;
  reason: string;
  frames: string[];
}

export interface ShiftHandover {
  generated_at: string;
  summary: ShiftSummary;
  escalated: TriageRow[];
  overridden: TriageRow[];
  approved: TriageRow[];
  awaiting: TriageRow[];
  contradicted_official: HandoverReport[];
  contradicted_third_party: number;
}

/** Shift simulation (GET /api/impact): a model of operator time, not evidence. Times are minutes of day. */
export interface HandlingTime {
  minutes: number;
  source: "ölçüm" | "kronometre" | "varsayım";
  n: number;
}

export interface SimFrame {
  image_id: string;
  level: Level;
  zone: string;
  capture_time: string;
  capture_min: number;
  eta_min: number | null;
  arrival_min: number | null;
  manual_start: number;
  manual_done: number;
  system_start: number;
  system_done: number;
  manual_before: boolean | null;
  system_before: boolean | null;
}

export interface ImpactReport {
  manual: HandlingTime;
  system: HandlingTime;
  frames: SimFrame[];
  summary: {
    by_level: Record<"KRİTİK" | "YÜKSEK", { with_eta: number; manual_before: number; system_before: number }>;
    manual_median_delay_min: number | null;
    system_median_delay_min: number | null;
  };
  assumptions: string[];
}

export type LngLat = [number, number];

export interface MapContext {
  base: { name: string; center: LngLat };
  zones: { name: string; label: string; center: LngLat }[];
  rings: { km: number; ring: LngLat[] }[];
  frames: {
    image_id: string;
    capture_time: string;
    zone: string;
    level: Level;
    score: number;
    center: LngLat;
    corners: LngLat[];
  }[];
}

export interface TrackPath {
  track_id: string;
  role: "vehicle" | "undetected" | "report";
  vehicle_ref?: string;
  label?: Label;
  score?: number;
  /** Vehicle level from config thresholds (backend); colours follow calibration. */
  level?: Level;
  points: [number, number, number][]; // [t_min, lat, lon]
}

export interface ReportPin {
  report_id: string;
  t_min: number;
  time: string;
  lat: number;
  lon: number;
  verdict: VerdictT;
  related_tracks: string[];
}

export interface FrameTracks {
  window: { start: number; end: number };
  radius_m: number;
  tracks: TrackPath[];
  report_pins: ReportPin[];
  vehicle_levels: Record<string, Level>;
}

export interface Health {
  detector: string;
  detector_fallback: string | null;
  llm: { provider: string; model: string; error: string | null };
  budget: { spent_usd: number; stop_usd: number; ratio: number };
  warmup: { done: number; total: number };
}

export interface TraceStep {
  step: string;
  duration_ms: number;
  cache_hit: boolean | null;
  input_summary: unknown;
  output_summary: unknown;
  error: string | null;
  llm?: { model: string; tokens_in: number; tokens_out: number; cached: boolean };
  grounding?: { checked: number; failed: string[] };
}

/** NDJSON events of POST /api/frames/{id}/evaluate/stream (live run). */
export type LiveEvent =
  | { type: "start"; step: string }
  | ({ type: "step" } & TraceStep)
  | { type: "packet"; run_id: string; packet: EvidencePacket }
  | { type: "result"; result: EvaluationResult; decision: Decision | null }
  | { type: "error"; detail: string };

/** Live run progress on the frame page: steps finished so far and the one running now. */
export interface LiveRun {
  current: string | null;
  done: TraceStep[];
}

export interface ToolCallRecord {
  name: string;
  arguments: Record<string, unknown>;
  summary: string;
  duration_ms: number;
  error: string | null;
}

export interface ChatTurn {
  answer: string;
  tool_calls: ToolCallRecord[];
  grounded: boolean;
  unverified: string[];
  llm_calls: number;
  duration_ms: number;
  note: string | null;
  run_id: string;
}
