// Vehicle view of the main map: one marker per vehicle of the day, moved along its track by the shared clock, with
// a short trail. Class silhouette and level colour come from GET /api/vehicles; tracks no frame detected are grey
// dots. Imperative on purpose: the clock ticks every animation frame and only these markers move.
import type { Map as MLMap, Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { Clock } from "../lib/clock";
import { positionOf, threatAt, trailOf, visibleAt } from "../lib/dayVehicles";
import { LABEL_TR, LEVEL_CLASS, LEVEL_COLOR, dec } from "../lib/format";
import { classSymbol } from "../lib/symbols";
import type { DayVehicle, Level } from "../lib/types";
import { fc, htmlMarker, line, setGeo } from "./MapView";

const TRAIL_EVERY_MS = 200; // trails are redrawn at most 5× a second; markers move every frame

function describe(v: DayVehicle, now: { score: number; level: Level } | null): string {
  if (!v.label || !v.level || !now) return `${v.track_id} · hiçbir karede tespit edilmedi`;
  const track = v.track_id ?? "hareket kaydı yok";
  return (
    `${v.vehicle_ref} ${LABEL_TR[v.label]} · ${track} · şu an skor ${now.score} (${now.level}) · ` +
    `${v.image_id} çekiminde ${v.score} · güven ${dec(v.conf ?? 0, 2)}`
  );
}

export function useVehicleLayer({
  map,
  ready,
  vehicles,
  enabled,
  threshold,
  clock,
  onSelect,
  onHover,
  onHoverOut,
}: {
  map: MLMap | null;
  ready: number; // bumps after every style (re)load: layers and markers are rebuilt then
  vehicles: DayVehicle[] | null;
  enabled: boolean;
  threshold: number;
  clock: Clock;
  onSelect: (imageId: string) => void;
  /** Pointer on a vehicle: preview that vehicle's own card next to it (its score, not its frame's). */
  onHover: (v: DayVehicle, at: [number, number]) => void;
  onHoverOut: () => void;
}) {
  const markers = useRef<Map<string, Marker>>(new Map());
  const thr = useRef(threshold);
  thr.current = threshold;
  const cb = useRef({ onSelect, onHover, onHoverOut });
  cb.current = { onSelect, onHover, onHoverOut };
  const redraw = useRef<() => void>(() => {});

  useEffect(() => {
    if (!map || !enabled || !vehicles) return;
    setGeo(map, "veh-trails", fc([]));
    if (!map.getLayer("veh-trails"))
      map.addLayer({
        id: "veh-trails",
        type: "line",
        source: "veh-trails",
        layout: { "line-cap": "round" },
        paint: { "line-color": ["get", "color"], "line-width": 2, "line-opacity": 0.55 },
      });
    for (const v of vehicles) {
      const known = !!(v.label && v.level);
      const pos = v.points[0];
      const m = htmlMarker(
        map,
        [pos[2], pos[1]],
        known ? classSymbol(v.label!) : "",
        known ? `mk mk-v ${LEVEL_CLASS[v.level!]}${v.track_id ? "" : " mk-v-still"}` : "mk-vdot",
        v.image_id ? () => cb.current.onSelect(v.image_id!) : undefined,
      );
      const el = m.getElement();
      el.dataset.vehicle = v.id;
      el.classList.add("mk-hidden");
      if (v.image_id) {
        el.addEventListener("mouseenter", () => {
          const p = m.getLngLat();
          cb.current.onHover(v, [p.lng, p.lat]);
        });
        el.addEventListener("mouseleave", () => cb.current.onHoverOut());
      }
      markers.current.set(v.id, m);
    }

    let lastTrail = 0;
    const draw = (force = false) => {
      const { t } = clock.get();
      const trails = [];
      for (const v of vehicles) {
        const m = markers.current.get(v.id);
        if (!m) continue;
        const el = m.getElement();
        const on = visibleAt(v, t, thr.current);
        el.classList.toggle("mk-hidden", !on);
        if (!on) continue;
        const p = positionOf(v, t);
        if (p) m.setLngLat(p);
        // Real-time threat: the level at this moment (backend timeline); re-classed only when it changes.
        const now = threatAt(v, t);
        const key = now ? `${now.level}|${now.score}` : "";
        if (el.dataset.threat !== key) {
          if (now && v.label) {
            el.classList.remove(...Object.values(LEVEL_CLASS));
            el.classList.add(LEVEL_CLASS[now.level]);
          }
          el.dataset.threat = key;
          el.title = describe(v, now);
        }
        if (now && v.track_id) trails.push(line(trailOf(v, t), { color: LEVEL_COLOR[now.level] }));
      }
      const now = performance.now();
      if (force || now - lastTrail > TRAIL_EVERY_MS) {
        lastTrail = now;
        setGeo(map, "veh-trails", fc(trails.filter((f) => (f.geometry as { coordinates: unknown[] }).coordinates.length > 1)));
      }
    };
    redraw.current = () => draw(true);
    draw(true);
    const unsub = clock.subscribe(() => draw(!clock.get().playing));
    return () => {
      unsub();
      markers.current.forEach((m) => m.remove());
      markers.current.clear();
      try {
        if (map.getSource("veh-trails")) setGeo(map, "veh-trails", fc([]));
      } catch {
        /* the map is already gone (page left) */
      }
      redraw.current = () => {};
    };
  }, [map, ready, vehicles, enabled, clock]);

  useEffect(() => redraw.current(), [threshold]);
}
