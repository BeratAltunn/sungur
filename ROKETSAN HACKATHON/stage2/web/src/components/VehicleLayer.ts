// Vehicle view of the main map: one marker per vehicle of the day, moved along its track by the shared clock, with
// a short trail. Class silhouette and level colour come from GET /api/vehicles; tracks no frame detected are grey
// dots. Imperative on purpose: the clock ticks every animation frame and only these markers move.
import type { Map as MLMap, Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { Clock } from "../lib/clock";
import { positionOf, trailOf, visibleAt } from "../lib/dayVehicles";
import { LABEL_TR, LEVEL_CLASS, LEVEL_COLOR, dec } from "../lib/format";
import { classSymbol } from "../lib/symbols";
import type { DayVehicle } from "../lib/types";
import { fc, htmlMarker, line, setGeo } from "./MapView";

const TRAIL_EVERY_MS = 200; // trails are redrawn at most 5× a second; markers move every frame

function describe(v: DayVehicle): string {
  if (!v.label || !v.level) return `${v.track_id} · hiçbir karede tespit edilmedi`;
  const track = v.track_id ?? "hareket kaydı yok";
  return `${v.vehicle_ref} ${LABEL_TR[v.label]} · ${track} · ${v.image_id} · skor ${v.score} · ${v.level} · güven ${dec(v.conf ?? 0, 2)}`;
}

export function useVehicleLayer({
  map,
  ready,
  vehicles,
  enabled,
  threshold,
  clock,
  onSelect,
}: {
  map: MLMap | null;
  ready: number; // bumps after every style (re)load: layers and markers are rebuilt then
  vehicles: DayVehicle[] | null;
  enabled: boolean;
  threshold: number;
  clock: Clock;
  onSelect: (imageId: string) => void;
}) {
  const markers = useRef<Map<string, Marker>>(new Map());
  const thr = useRef(threshold);
  thr.current = threshold;
  const select = useRef(onSelect);
  select.current = onSelect;
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
        v.image_id ? () => select.current(v.image_id!) : undefined,
      );
      const el = m.getElement();
      el.dataset.vehicle = v.id;
      el.title = describe(v);
      el.classList.add("mk-hidden");
      markers.current.set(v.id, m);
    }

    let lastTrail = 0;
    const draw = (force = false) => {
      const { t } = clock.get();
      const trails = [];
      for (const v of vehicles) {
        const m = markers.current.get(v.id);
        if (!m) continue;
        const on = visibleAt(v, t, thr.current);
        m.getElement().classList.toggle("mk-hidden", !on);
        if (!on) continue;
        const p = positionOf(v, t);
        if (p) m.setLngLat(p);
        if (v.level && v.track_id) trails.push(line(trailOf(v, t), { color: LEVEL_COLOR[v.level] }));
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
