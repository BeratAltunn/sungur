// Display-only geometry for the time slider. Evidence (distances, verdicts, ETA) is never computed here.
import type { LngLat } from "./types";

type Pt = [number, number, number]; // [t_min, lat, lon]

/** Position at time t by linear interpolation between the 5-minute track points (null if not covered). */
export function positionAt(points: Pt[], t: number): LngLat | null {
  if (!points.length || t < points[0][0] || t > points[points.length - 1][0]) return null;
  for (let i = 0; i < points.length - 1; i++) {
    const [t0, la0, lo0] = points[i];
    const [t1, la1, lo1] = points[i + 1];
    if (t >= t0 && t <= t1) {
      const a = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
      return [lo0 + a * (lo1 - lo0), la0 + a * (la1 - la0)];
    }
  }
  const last = points[points.length - 1];
  return [last[2], last[1]];
}

/** Path travelled up to time t (for the "so far" line). */
export function pathUntil(points: Pt[], t: number): LngLat[] {
  const out: LngLat[] = points.filter((p) => p[0] <= t).map((p) => [p[2], p[1]]);
  const cur = positionAt(points, t);
  if (cur) out.push(cur);
  return out;
}

export const fullPath = (points: Pt[]): LngLat[] => points.map((p) => [p[2], p[1]]);

/** Circle polygon around a point (equirectangular, fine at a few hundred metres). */
export function circle(center: LngLat, radiusM: number, n = 48): LngLat[] {
  const [lon, lat] = center;
  const kx = 111320 * Math.cos((lat * Math.PI) / 180);
  const out: LngLat[] = [];
  for (let i = 0; i <= n; i++) {
    const a = (2 * Math.PI * i) / n;
    out.push([lon + (radiusM * Math.sin(a)) / kx, lat + (radiusM * Math.cos(a)) / 111320]);
  }
  return out;
}

/** North–south and east–west lines every stepM around a point, out to halfM: a reference grid that shows the
 *  map plane's tilt and rotation (equirectangular, fine over ~20 km). */
export function grid(center: LngLat, halfM: number, stepM: number): LngLat[][] {
  const [lon, lat] = center;
  const kx = 111320 * Math.cos((lat * Math.PI) / 180);
  const n = Math.floor(halfM / stepM);
  const [dx, dy] = [halfM / kx, halfM / 111320];
  const out: LngLat[][] = [];
  for (let i = -n; i <= n; i++) {
    const x = lon + (i * stepM) / kx;
    const y = lat + (i * stepM) / 111320;
    out.push([[x, lat - dy], [x, lat + dy]], [[lon - dx, y], [lon + dx, y]]);
  }
  return out;
}

export function bounds(points: LngLat[]): [LngLat, LngLat] {
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of points) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}
