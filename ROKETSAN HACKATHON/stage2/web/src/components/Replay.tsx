// Shift replay on the triage screen: a simulated clock runs through the day, frames join the queue at their
// capture time, and two lanes show where a single operator would be by hand (FIFO) and with NÖBETÇİ (risk
// order). All times come from GET /api/impact (backend simulation); this file only compares them with the clock.
import { useEffect, useMemo, useState } from "react";
import { go } from "../App";
import { api } from "../lib/api";
import { dec, hhmm, storage, zoneName } from "../lib/format";
import type { ImpactReport, SimFrame } from "../lib/types";
import { LevelBadge } from "./ui";

export interface ReplayState {
  t: number; // simulated clock, minutes of day
  playing: boolean;
  speed: number; // simulated minutes per real second
}

const SPEEDS = [1, 5, 15];
const NEW_WINDOW_MIN = 10; // "YENİ" badge
const ALERT_WINDOW_MIN = 20; // how long a KRİTİK arrival stays in the alert strip

/** Replay state (persisted, so opening a frame and coming back keeps the clock) and the simulation. */
export function useReplay() {
  const [state, setState] = useState<ReplayState | null>(() =>
    window.location.hash.includes("replay=1") ? { t: -1, playing: false, speed: 5 } : storage.get("replay", null),
  );
  const [sim, setSim] = useState<ImpactReport | null>(null);

  useEffect(() => {
    if (!state || sim) return;
    api
      .impact()
      .then((r) => {
        setSim(r);
        setState((s) => (s && s.t < 0 ? { ...s, t: r.frames[0].capture_min - 5 } : s));
      })
      .catch(() => setState(null));
  }, [state, sim]);

  const bounds = useMemo(() => {
    if (!sim) return null;
    const caps = sim.frames.map((f) => f.capture_min);
    return { start: Math.min(...caps) - 5, end: Math.max(...caps) + 15 };
  }, [sim]);

  useEffect(() => {
    if (state && state.t >= 0) storage.set("replay", { ...state, playing: false });
  }, [state]);

  // One step per second (MIL-STD-1472: dynamic values update at most once a second); `speed` = sim minutes per step.
  useEffect(() => {
    if (!state?.playing || !bounds) return;
    const h = window.setInterval(() => {
      setState((s) => {
        if (!s) return s;
        const t = Math.min(s.t + s.speed, bounds.end);
        return { ...s, t, playing: t < bounds.end };
      });
    }, 1000);
    return () => window.clearInterval(h);
  }, [state?.playing, bounds]);

  const arrived = useMemo(() => {
    if (!state || !sim || state.t < 0) return null;
    return new Set(sim.frames.filter((f) => f.capture_min <= state.t).map((f) => f.image_id));
  }, [state, sim]);

  const isNew = (id: string) => {
    const f = sim?.frames.find((x) => x.image_id === id);
    return !!(f && state && state.t - f.capture_min < NEW_WINDOW_MIN);
  };

  return {
    state,
    sim,
    bounds,
    arrived, // null when replay is off (queue shows the whole day)
    isNew,
    start: () => {
      setSim(null);
      setState({ t: -1, playing: false, speed: 5 });
    },
    stop: () => {
      storage.set("replay", null);
      setState(null);
      if (window.location.hash.includes("replay=1")) window.history.replaceState(null, "", "#/");
    },
    set: (patch: Partial<ReplayState>) => setState((s) => (s ? { ...s, ...patch } : s)),
  };
}

function Lane({ name, sim, frames, t, which }: { name: string; sim: number; frames: SimFrame[]; t: number; which: "manual" | "system" }) {
  const start = (f: SimFrame) => (which === "manual" ? f.manual_start : f.system_start);
  const done = (f: SimFrame) => (which === "manual" ? f.manual_done : f.system_done);
  const current = frames.find((f) => start(f) <= t && t < done(f));
  const waiting = frames.filter((f) => f.capture_min <= t && start(f) > t).length;
  const decided = frames.filter((f) => done(f) <= t).length;
  return (
    <div className={`lane lane-${which}`}>
      <span className={which === "manual" ? "mk-man" : "mk-sys"} aria-hidden />
      <b>{name}</b>
      <span className="muted small">{dec(sim)} dk/kare</span>
      <span>{current ? <>inceleniyor: <span className="mono">{current.image_id}</span></> : <span className="muted">boşta</span>}</span>
      <span className={waiting ? "attn-text" : "muted"}>{waiting} kare bekliyor</span>
      <span className="muted">{decided} karar</span>
    </div>
  );
}

/** What happens to a freshly arrived KRİTİK frame: vehicles' projected arrival vs the two decisions. */
function Alert({ f, t }: { f: SimFrame; t: number }) {
  const status = (doneAt: number, startAt: number, before: boolean | null) =>
    t >= doneAt
      ? `karar ${hhmm(doneAt)} ${before ? "✓ varıştan önce" : "✗ varıştan sonra"}`
      : t >= startAt
        ? "inceleniyor…"
        : "kuyrukta bekliyor";
  const arr = f.arrival_min!;
  return (
    <div className="replay-alert" onClick={() => go(`/frame/${f.image_id}`)} role="status">
      <LevelBadge level={f.level} size="sm" />
      <span className="mono">
        {f.capture_time} {f.image_id}
      </span>
      <span>{zoneName(f.zone)}</span>
      <span className={t >= arr ? "vd-bad" : ""}>
        {t >= arr ? `araçlar üste vardı (~${hhmm(arr)})` : `araçlar ~${hhmm(arr)}'te üste · ${dec(arr - t)} dk`}
      </span>
      <span>
        <span className="mk-sys" aria-hidden /> NÖBETÇİ: {status(f.system_done, f.system_start, f.system_before)}
      </span>
      <span>
        <span className="mk-man" aria-hidden /> Elle: {status(f.manual_done, f.manual_start, f.manual_before)}
      </span>
    </div>
  );
}

export function ReplayBar({ r }: { r: ReturnType<typeof useReplay> }) {
  const { state, sim, bounds } = r;
  if (!state) return null;
  if (!sim || !bounds || state.t < 0) return <section className="replay">Vardiya simülasyonu yükleniyor…</section>;
  const t = state.t;
  const alerts = sim.frames.filter(
    (f) => f.level === "KRİTİK" && f.arrival_min !== null && f.capture_min <= t && t - f.capture_min < ALERT_WINDOW_MIN,
  );
  return (
    <section className="replay" aria-label="Vardiya oynatma">
      <div className="replay-controls">
        <span className="shift-title">Vardiya oynatma</span>
        <button className="btn btn-sm" onClick={() => r.set({ playing: !state.playing })} aria-label={state.playing ? "Durdur" : "Oynat"}>
          {state.playing ? "Durdur" : "Oynat"}
        </button>
        <span className="mono big" aria-live="off">
          {hhmm(t)}
        </span>
        <input
          type="range"
          min={bounds.start}
          max={bounds.end}
          step={1}
          value={Math.round(t)}
          onChange={(e) => r.set({ t: Number(e.target.value), playing: false })}
          aria-label="Simülasyon saati"
          aria-valuetext={hhmm(t)}
        />
        <select value={state.speed} onChange={(e) => r.set({ speed: Number(e.target.value) })} aria-label="Hız">
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s} dk/sn
            </option>
          ))}
        </select>
        <a className="btn btn-ghost btn-sm" href="#/impact">
          Etki özeti →
        </a>
        <button className="btn btn-ghost btn-sm" onClick={r.stop}>
          ✕ Kapat
        </button>
      </div>
      <div className="lanes">
        <Lane name="Elle (geliş sırası)" sim={sim.manual.minutes} frames={sim.frames} t={t} which="manual" />
        <Lane name="NÖBETÇİ (risk sırası)" sim={sim.system.minutes} frames={sim.frames} t={t} which="system" />
      </div>
      {alerts.map((f) => (
        <Alert key={f.image_id} f={f} t={t} />
      ))}
      <p className="muted small replay-note">
        Simülasyon: kareler çekim saatinde kuyruğa düşer; tek operatör, kare başına süreler {sim.manual.source}/
        {sim.system.source}. Ayrıntı ve varsayımlar: Etki özeti.
      </p>
    </section>
  );
}
