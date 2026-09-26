// Video-like time bar under the main map's vehicle view: play / pause, speed, a scrubber over the day with a tick at
// every frame's capture time, and the score threshold that thins the map. Reads and drives the shared clock.
import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { Clock } from "../lib/clock";
import { visibleAt } from "../lib/dayVehicles";
import { hhmm } from "../lib/format";
import type { DayVehicle } from "../lib/types";

const SPEEDS = [1, 2, 5, 10]; // simulated minutes per second

/** A frame's capture moment on the bar (no threat level: the vehicles carry it). */
export interface Tick {
  image_id: string;
  t: number;
  time: string;
}

export function TimeBar({
  clock,
  window: w,
  ticks,
  vehicles,
  threshold,
  onThreshold,
  onTick,
}: {
  clock: Clock;
  window: { start: number; end: number };
  ticks: Tick[];
  vehicles: DayVehicle[];
  threshold: number;
  onThreshold: (v: number) => void;
  onTick: (imageId: string) => void;
}) {
  const { t, playing, speed } = useSyncExternalStore(clock.subscribe, clock.get);

  // Playback: advance by real elapsed time (smooth at any frame rate), stop at the end of the day.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const step = (now: number) => {
      const s = clock.get();
      const next = Math.min(s.t + ((now - last) / 1000) * s.speed, w.end);
      last = now;
      clock.set({ t: next, playing: next < w.end });
      if (next < w.end) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, clock, w.end]);

  const shown = useMemo(() => vehicles.filter((v) => visibleAt(v, t, threshold)).length, [vehicles, t, threshold]);
  const pct = (x: number) => `${((x - w.start) / (w.end - w.start)) * 100}%`;
  const play = () => clock.set({ playing: !playing, t: t >= w.end ? w.start : t });

  return (
    <section className="timebar hud-panel" aria-label="Zaman çubuğu">
      <div className="timebar-row">
        <button className="btn btn-sm timebar-play" onClick={play} aria-label={playing ? "Zamanı durdur" : "Zamanı oynat"} title="Zamanı oynat / durdur (Space)">
          {playing ? "❚❚" : "▶"}
        </button>
        <span className="mono timebar-now" aria-live="off">
          {hhmm(t)}
        </span>
        <div className="timebar-track">
          <input
            type="range"
            min={w.start}
            max={w.end}
            step={0.5}
            value={t}
            onChange={(e) => clock.set({ t: Number(e.target.value), playing: false })}
            aria-label="Zaman çubuğu saati"
            aria-valuetext={hhmm(t)}
          />
          {ticks.map((k) => (
            <button
              key={k.image_id}
              className="timebar-tick"
              style={{ left: pct(k.t) }}
              title={`${k.image_id} · ${k.time} çekimi`}
              aria-label={`${k.time} ${k.image_id}: çekim saatine git`}
              onClick={() => {
                clock.set({ t: k.t, playing: false });
                onTick(k.image_id);
              }}
            />
          ))}
        </div>
        <select value={speed} onChange={(e) => clock.set({ speed: Number(e.target.value) })} aria-label="Oynatma hızı">
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s} dk/sn
            </option>
          ))}
        </select>
      </div>
      <div className="timebar-row timebar-sub">
        <label className="timebar-thr">
          Eşik: skor ≥ <b className="mono">{threshold}</b>
          <input type="range" min={0} max={100} step={5} value={threshold} onChange={(e) => onThreshold(Number(e.target.value))} aria-label="Tehdit skoru eşiği" />
        </label>
        <span className="muted mono">{shown} araç</span>
        <span className="muted small">
          {threshold === 0 ? "gri nokta: hiçbir karede tespit edilmemiş iz" : "eşik altındaki ve tespit edilmemiş araçlar gizli"}
        </span>
      </div>
    </section>
  );
}
