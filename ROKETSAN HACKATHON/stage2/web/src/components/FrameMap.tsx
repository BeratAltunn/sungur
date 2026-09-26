import type { Map as MLMap, Marker } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { SOURCE_TR, VERDICT_CLASS, VERDICT_ICON, dec, flyMs, hhmm } from "../lib/format";
import { QUATREFOIL, baseSymbol, vehicleSymbol } from "../lib/symbols";
import { levelColor, token } from "../lib/theme";
import { bounds, circle, fullPath, pathUntil, positionAt } from "../lib/geo";
import type { FrameInfo, FrameTracks, LngLat, MapContext, ReportVerification, TrackPath } from "../lib/types";
import { LayerMenu, useLayers } from "./LayerMenu";
import { MapView, fc, htmlMarker, line, polygon, setGeo } from "./MapView";
import { RefText, VerdictBadge } from "./ui";

export type Focus = { kind: "track"; id: string } | { kind: "report"; id: string } | null;

type FrameLayer = "others" | "pins" | "projections" | "rings";
const FRAME_LAYERS: { key: FrameLayer; label: string }[] = [
  { key: "others", label: "Diğer izler (raporla ilgili, tespitsiz)" },
  { key: "pins", label: "Rapor işaretleri" },
  { key: "projections", label: "Tahmini varış çizgileri" },
  { key: "rings", label: "Mesafe halkaları" },
];

interface Props {
  ctx: MapContext;
  frame: FrameInfo;
  imageUrl: string;
  data: FrameTracks;
  t: number;
  focus: Focus;
  onFocus: (f: Focus) => void;
  /** Blind labelling: vehicle paths in one neutral colour (colours would reveal scores). */
  blind?: boolean;
}

export function FrameMap({ ctx, frame, imageUrl, data, t, focus, onFocus, blind = false }: Props) {
  // Level colour only for the frame's own vehicles; every other path is a neutral (blind mode: one neutral).
  const trackColor = (tr: TrackPath) =>
    tr.role === "vehicle"
      ? blind || !tr.level
        ? token("--text-2")
        : levelColor(tr.level)
      : tr.role === "undetected"
        ? token("--muted")
        : token("--line-strong");
  const mapRef = useRef<MLMap | null>(null);
  const { layers, toggle } = useLayers<FrameLayer>("layers_frame", { others: true, pins: true, projections: true, rings: true });
  const vehicleMarkers = useRef<Record<string, Marker>>({});
  const pinMarkers = useRef<Record<string, Marker>>({});
  const [ready, setReady] = useState(0);
  const c = frame.corners;
  const frameCorners: LngLat[] = [c.top_left, c.top_right, c.bottom_right, c.bottom_left].map(([la, lo]) => [lo, la]);

  const focusedTrack = focus?.kind === "track" ? focus.id : null;
  const pin = focus?.kind === "report" ? data.report_pins.find((p) => p.report_id === focus.id) ?? null : null;
  // Layer "others" hides tracks that are not this frame's vehicles; a focused track or report's tracks always show.
  const trackShown = (tr: TrackPath) =>
    layers.others || tr.role === "vehicle" || tr.track_id === focusedTrack || !!pin?.related_tracks.includes(tr.track_id);

  const fitAll = () => {
    const map = mapRef.current;
    if (!map) return;
    const pts: LngLat[] = [...frameCorners, ...data.tracks.flatMap((tr) => fullPath(tr.points))];
    map.fitBounds(bounds(pts), { padding: 48, duration: flyMs(600), maxZoom: 16 });
  };
  const fitFrame = () => mapRef.current?.fitBounds(bounds(frameCorners), { padding: 24, duration: flyMs(600) });

  const onReady = (map: MLMap) => {
    mapRef.current = map;
    Object.values(vehicleMarkers.current).forEach((m) => m.remove());
    Object.values(pinMarkers.current).forEach((m) => m.remove());
    vehicleMarkers.current = {};
    pinMarkers.current = {};

    setGeo(map, "rings", fc(ctx.rings.map((r) => line(r.ring))));
    map.addLayer({ id: "rings", type: "line", source: "rings", paint: { "line-color": token("--line"), "line-dasharray": [3, 3] } });
    map.addSource("frame-img", { type: "image", url: imageUrl, coordinates: frameCorners as never });
    map.addLayer({ id: "frame-img", type: "raster", source: "frame-img", paint: { "raster-opacity": 0.95 } });
    setGeo(map, "frame-outline", fc([line([...frameCorners, frameCorners[0]])]));
    map.addLayer({ id: "frame-outline", type: "line", source: "frame-outline", paint: { "line-color": token("--text-2"), "line-width": 1.5 } });

    for (const id of ["paths-full", "paths-sofar", "report-circle", "links"]) setGeo(map, id, fc([]));
    map.addLayer({
      id: "paths-full",
      type: "line",
      source: "paths-full",
      paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.35 },
    });
    map.addLayer({
      id: "paths-sofar",
      type: "line",
      source: "paths-sofar",
      paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-opacity": 0.95 },
    });
    map.addLayer({ id: "report-circle-fill", type: "fill", source: "report-circle", paint: { "fill-color": token("--text"), "fill-opacity": 0.08 } });
    map.addLayer({ id: "report-circle", type: "line", source: "report-circle", paint: { "line-color": token("--text"), "line-width": 1.5 } });
    map.addLayer({
      id: "links",
      type: "line",
      source: "links",
      paint: { "line-color": token("--text"), "line-width": 1, "line-dasharray": [2, 2], "line-opacity": 0.8 },
    });

    // Projection vectors (vehicle at capture → base), drawn under the markers.
    setGeo(map, "projections", fc([]));
    map.addLayer({
      id: "projections",
      type: "line",
      source: "projections",
      paint: { "line-color": ["get", "color"], "line-width": 2, "line-dasharray": [1.5, 1.5], "line-opacity": 0.9 },
    });

    htmlMarker(map, ctx.base.center, baseSymbol(ctx.base.name), "mk mk-base");
    const activeZone = ctx.zones.find((z) => z.name === frame.zone);
    if (activeZone) {
      htmlMarker(map, activeZone.center, activeZone.label, "mk mk-zone");
    }
    for (const tr of data.tracks) {
      const label = tr.vehicle_ref ? `${tr.vehicle_ref}` : tr.track_id;
      const m = htmlMarker(map, [0, 0], vehicleSymbol(label), `mk mk-veh mk-${tr.role}`, () => onFocusRef.current({ kind: "track", id: tr.track_id }));
      m.getElement().style.setProperty("--c", trackColor(tr));
      m.getElement().title = `${tr.vehicle_ref ?? ""} ${tr.track_id}`.trim();
      vehicleMarkers.current[tr.track_id] = m;
    }
    for (const p of data.report_pins) {
      const m = htmlMarker(
        map,
        [p.lon, p.lat],
        `<span>${VERDICT_ICON[p.verdict]}</span>${p.report_id}`,
        `mk mk-pin ${VERDICT_CLASS[p.verdict]}`,
        () => onFocusRef.current({ kind: "report", id: p.report_id }),
      );
      m.getElement().title = `${p.report_id} · ${p.time} · ${p.verdict}`;
      pinMarkers.current[p.report_id] = m;
    }
    fitAll();
    setReady((r) => r + 1);
  };
  const onFocusRef = useRef(onFocus);
  onFocusRef.current = onFocus;

  // Time slider: move vehicles, extend the "so far" paths. Pure display; runs every tick.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("paths-sofar")) return;
    setGeo(
      map,
      "paths-full",
      fc(data.tracks.filter(trackShown).map((tr) => line(fullPath(tr.points), { color: trackColor(tr) }))),
    );
    setGeo(
      map,
      "paths-sofar",
      fc(
        data.tracks.filter(trackShown).map((tr) =>
          line(pathUntil(tr.points, t), {
            color: tr.track_id === focusedTrack ? token("--text") : trackColor(tr),
            width: tr.track_id === focusedTrack ? 4 : tr.role === "vehicle" ? 2.5 : 1.5,
          }),
        ),
      ),
    );
    for (const tr of data.tracks) {
      const m = vehicleMarkers.current[tr.track_id];
      const pos = positionAt(tr.points, t);
      const el = m.getElement();
      el.style.display = pos && trackShown(tr) ? "" : "none";
      if (pos) m.setLngLat(pos);
      el.classList.toggle("mk-focus", tr.track_id === focusedTrack || !!pin?.related_tracks.includes(tr.track_id));
    }
    // selected report: its radius and dashed links to the vehicles it is about, at the slider time
    if (pin) {
      setGeo(map, "report-circle", fc([polygon(circle([pin.lon, pin.lat], data.radius_m))]));
      const links = data.tracks
        .filter((tr) => pin.related_tracks.includes(tr.track_id))
        .map((tr) => positionAt(tr.points, t))
        .filter((p): p is LngLat => !!p)
        .map((p) => line([[pin.lon, pin.lat], p]));
      setGeo(map, "links", fc(links));
    } else {
      setGeo(map, "report-circle", fc([]));
      setGeo(map, "links", fc([]));
    }
    for (const [id, m] of Object.entries(pinMarkers.current)) {
      m.getElement().classList.toggle("mk-focus", id === pin?.report_id);
      m.getElement().style.display = layers.pins || id === pin?.report_id ? "" : "none";
    }
    if (map.getLayer("rings")) map.setLayoutProperty("rings", "visibility", layers.rings ? "visible" : "none");
    // Projection is from the capture moment: shown only when the slider is there.
    const atCapture = t >= data.window.end;
    setGeo(
      map,
      "projections",
      fc(
        atCapture && layers.projections
          ? data.projections.map((p) =>
              line([[p.lon, p.lat], ctx.base.center], { color: blind ? token("--text-2") : levelColor(p.level) }),
            )
          : [],
      ),
    );

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t, focusedTrack, pin, data, ready, blind, ctx, layers]);

  // Focusing a report frames the pin and its vehicles so the gap is visible at a glance.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !pin) return;
    const pts: LngLat[] = [[pin.lon, pin.lat]];
    for (const tr of data.tracks)
      if (pin.related_tracks.includes(tr.track_id)) {
        const p = positionAt(tr.points, pin.t_min);
        if (p) pts.push(p);
      }
    map.fitBounds(bounds(pts), { padding: 70, duration: flyMs(700), maxZoom: 15 });
  }, [pin, data]);

  return (
    <div className="frame-map">
      <MapView
        onReady={onReady}
        initial={{ center: [frame.center_lon, frame.center_lat], zoom: 13 }}
        controls={<LayerMenu defs={FRAME_LAYERS} layers={layers} onToggle={toggle} />}
      />
      {/* Projection readout (HUD): the soonest arrival, first in the backend's order; vectors are on the map. */}
      {data.projections.length > 0 && (
        <div className={`map-hud ${t >= data.window.end ? "" : "map-hud-off"}`} role="status">
          <span className="legend-dash" aria-hidden />
          {data.projections.length > 1 ? `${data.projections.length} araç üsse yaklaşıyor · ` : ""}
          en kısa ETA <b>~{dec(data.projections[0].eta_min)} dk</b> ({data.projections[0].vehicle_ref})
          {t < data.window.end && <span className="muted"> · çekim anında geçerli</span>}
        </div>
      )}
      <div className="map-legend" aria-label="Harita işaretleri">
        <span>
          <span className="sym-base sym-base-sm" aria-hidden>
            ÜS
          </span>{" "}
          dost (üs)
        </span>
        <span>
          <svg className="sym sym-legend" viewBox="-1 -1 22 22" aria-hidden>
            <path d={QUATREFOIL} />
          </svg>{" "}
          araç: kimliği belirsiz{blind ? "" : ", renk = risk"}
        </span>
        <span>
          <span className="legend-dash" aria-hidden /> tahmini varış (çekim anı)
        </span>
      </div>
      <div className="map-actions">
        <button className="btn btn-ghost btn-sm" onClick={fitAll}>
          Tüm izler
        </button>
        <button className="btn btn-ghost btn-sm" onClick={fitFrame}>
          Kareye odaklan
        </button>
      </div>
    </div>
  );
}

/** The focused report on the map: what it claims and the verifier's verdict at the report's own time.
 *  Text and reason come verbatim from the evidence packet; nothing is computed here. */
export function ReportCallout({
  report,
  atReportTime,
  onSeek,
  onClose,
  onRef,
}: {
  report: ReportVerification;
  atReportTime: boolean;
  onSeek: () => void;
  onClose: () => void;
  onRef: (id: string) => void;
}) {
  return (
    <div className={`callout ${VERDICT_CLASS[report.verdict]}-callout`} role="status" aria-live="polite">
      <div className="callout-head">
        <VerdictBadge verdict={report.verdict} />
        <span className="mono">
          {report.report_id} · {report.time}
        </span>
        <span className={`pill pill-dim ${report.source === "official" ? "" : "pill-3p"}`}>{SOURCE_TR[report.source]}</span>
        {report.identity_claim && <span className="pill pill-strong">kimlik iddiası</span>}
        <button className="btn btn-ghost btn-sm callout-close" onClick={onClose} aria-label="Raporu kapat">
          ✕
        </button>
      </div>
      <p className="callout-text">“{report.text}”</p>
      <p className="callout-reason">
        → <RefText text={report.reason} onRef={onRef} />
      </p>
      {!atReportTime && (
        <button className="btn btn-ghost btn-sm" onClick={onSeek}>
          Rapor saatine git ({report.time})
        </button>
      )}
    </div>
  );
}

interface SliderProps {
  data: FrameTracks;
  t: number;
  onChange: (t: number) => void;
  playing: boolean;
  onPlay: () => void;
  focusReport: string | null;
  onPickReport: (id: string) => void;
}

export function TimeSlider({ data, t, onChange, playing, onPlay, focusReport, onPickReport }: SliderProps) {
  const { start, end } = data.window;
  const pct = (x: number) => `${((x - start) / (end - start)) * 100}%`;
  const before = end - t;
  return (
    <div className="slider" aria-label="Zaman kaydırıcısı">
      <button className="btn btn-ghost btn-sm" onClick={onPlay} aria-label={playing ? "Durdur" : "Oynat"}>
        {playing ? "Durdur" : "Oynat"}
      </button>
      <div className="slider-track">
        <input
          type="range"
          min={start}
          max={end}
          step={1}
          value={t}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-valuetext={hhmm(t)}
        />
        {data.report_pins.map((p) => (
          <button
            key={p.report_id}
            className={`tick ${VERDICT_CLASS[p.verdict]} ${focusReport === p.report_id ? "tick-focus" : ""}`}
            style={{ left: pct(p.t_min) }}
            onClick={() => onPickReport(p.report_id)}
            title={`${p.report_id} · ${p.time} · ${p.verdict}`}
          >
            {VERDICT_ICON[p.verdict]}
          </button>
        ))}
        <div className="slider-scale">
          <span>{hhmm(start)}</span>
          <span>{hhmm(end)} çekim</span>
        </div>
      </div>
      <div className="slider-now">
        <span className="mono big">{hhmm(t)}</span>
        <span className="muted">{before > 0 ? `çekimden ${before} dk önce` : "çekim anı"}</span>
      </div>
      <button className="btn btn-ghost btn-sm" onClick={() => onChange(end)} disabled={t === end}>
        Çekim anına dön
      </button>
    </div>
  );
}
