// Display rules for the main map's vehicle view. Positions between the 5-minute track points are interpolated for
// drawing only (like the frame page's time slider); scores and levels come from GET /api/vehicles.
import { positionAt } from "./geo";
import type { DayVehicle, Level, LngLat } from "./types";

/** A detection without a track is known only at its capture time; it is drawn this long either side of it. */
export const UNTRACKED_SHOW_MIN = 5;
/** Trail behind a moving vehicle. */
export const TRAIL_MIN = 20;

export const toMin = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

/** Score and level at time t: the backend's value at the latest track point ≤ t (before the first point, the first
 *  one). Null for tracks no frame detected. A lookup only; nothing is scored here. */
export function threatAt(v: DayVehicle, t: number): { score: number; level: Level } | null {
  const tl = v.timeline;
  if (!tl.length) return null;
  let i = 0;
  while (i + 1 < tl.length && tl[i + 1][0] <= t) i++;
  return { score: tl[i][1], level: tl[i][2] };
}

/** Shown at time t with the score threshold: inside its track window (or near its capture time when it has no
 *  track) and scored at least `threshold` at that moment. Tracks no frame detected show only at threshold 0. */
export function visibleAt(v: DayVehicle, t: number, threshold: number): boolean {
  if (threshold > 0 && (threatAt(v, t)?.score ?? -1) < threshold) return false;
  const first = v.points[0][0];
  const last = v.points[v.points.length - 1][0];
  return v.track_id ? first <= t && t <= last : Math.abs(t - first) <= UNTRACKED_SHOW_MIN;
}

export function positionOf(v: DayVehicle, t: number): LngLat | null {
  if (!v.track_id) return [v.points[0][2], v.points[0][1]];
  return positionAt(v.points, t);
}

/** Path over the last TRAIL_MIN minutes up to t (for the fading trail). */
export function trailOf(v: DayVehicle, t: number): LngLat[] {
  if (!v.track_id) return [];
  const out: LngLat[] = v.points.filter((p) => p[0] > t - TRAIL_MIN && p[0] <= t).map((p) => [p[2], p[1]]);
  const start = positionAt(v.points, Math.max(v.points[0][0], t - TRAIL_MIN));
  const now = positionAt(v.points, t);
  if (start) out.unshift(start);
  if (now) out.push(now);
  return out;
}
