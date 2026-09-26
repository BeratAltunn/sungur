import { useCallback, useEffect, useMemo, useState } from "react";
import { go } from "../App";
import { BriefPanel, DecisionBar, FrameHeader } from "../components/Brief";
import { type Focus, FrameMap, ReportCallout, TimeSlider } from "../components/FrameMap";
import { ImagePanel } from "../components/ImagePanel";
import { EvidenceTabs, type TabId } from "../components/Tabs";
import { ErrorState, Kbd, Loading, RefLabels, TopBar } from "../components/ui";
import { api, explain } from "../lib/api";
import { km, smooth, storage } from "../lib/format";
import type {
  Decision,
  EvaluationResult,
  EvidencePacket,
  FrameTracks,
  Health,
  LiveEvent,
  LiveRun,
  MapContext,
  TriageRow,
} from "../lib/types";

interface Props {
  id: string;
  health: Health | null;
  queue: TriageRow[] | null;
  onChanged: () => void;
}

const STEP_REVEAL_MS = 250;
const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

export function FramePage({ id, health, queue, onChanged }: Props) {
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [tracks, setTracks] = useState<FrameTracks | null>(null);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [res, setRes] = useState<EvaluationResult | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState<Focus>(null);
  const [tab, setTab] = useState<TabId>("why");
  const [toast, setToast] = useState<string | null>(null);
  const [live, setLive] = useState<LiveRun | null>(null);

  // Deterministic evidence first (fast), the LLM brief arrives after.
  const load = useCallback(() => {
    setError(null);
    Promise.all([api.packet(id), api.tracks(id), api.map()])
      .then(([p, tr, m]) => {
        setPacket(p);
        setTracks(tr);
        setMapCtx(m);
        setT(tr.window.end);
      })
      .catch((e) => setError(e));
    api
      .frame(id)
      .then((f) => {
        setRes(f.result);
        setPacket(f.result.packet);
        setDecision(f.decision);
        onChanged();
      })
      .catch((e) => setError(e));
  }, [id, onChanged]);
  useEffect(load, [load]);

  useEffect(() => {
    api.viewed(id).catch(() => undefined); // handling-time measurement; never blocks the page
    const seen = new Set(storage.get<string[]>("viewed", []));
    seen.add(id);
    storage.set("viewed", [...seen]);
  }, [id]);

  // Playback: one simulated minute per tick.
  useEffect(() => {
    if (!playing || !tracks) return;
    const h = window.setInterval(() => {
      setT((x) => {
        if (x >= tracks.window.end) {
          setPlaying(false);
          return x;
        }
        return x + 1;
      });
    }, 90);
    return () => window.clearInterval(h);
  }, [playing, tracks]);

  const trackOfVehicle = useMemo(() => {
    const m: Record<string, string> = {};
    for (const v of packet?.vehicles ?? []) if (v.track_id) m[v.ref] = v.track_id;
    return m;
  }, [packet]);

  const pickReport = useCallback(
    (rid: string) => {
      const pin = tracks?.report_pins.find((p) => p.report_id === rid);
      setFocus({ kind: "report", id: rid });
      setTab("reports");
      if (pin) {
        setPlaying(false);
        setT(pin.t_min);
      }
    },
    [tracks],
  );

  // Evidence chips: V1 / T0122 highlight the vehicle; R069 jumps the map and slider to that report's time.
  const onRef = useCallback(
    (ref: string) => {
      if (ref.startsWith("R")) pickReport(ref);
      else if (ref.startsWith("V")) setFocus(trackOfVehicle[ref] ? { kind: "track", id: trackOfVehicle[ref] } : null);
      else setFocus({ kind: "track", id: ref });
    },
    [pickReport, trackOfVehicle],
  );

  // Chips clicked in the chat panel arrive as a window event.
  useEffect(() => {
    const on = (e: Event) => onRef((e as CustomEvent<string>).detail);
    window.addEventListener("sentinel:ref", on);
    return () => window.removeEventListener("sentinel:ref", on);
  }, [onRef]);

  const activeRef = focus?.kind === "report" ? focus.id : focus?.kind === "track" ? focus.id : null;

  // After a decision the operator moves on: the next frame in risk order still waiting for a decision.
  const nextPending = useMemo(() => {
    const order = queue ?? [];
    const i = order.findIndex((r) => r.image_id === id);
    return [...order.slice(i + 1), ...order.slice(0, Math.max(i, 0))].find((r) => !r.decision && r.image_id !== id) ?? null;
  }, [queue, id]);

  // Keyboard: Esc back · J/K next/prev frame in the queue · Space play · A approve · E escalate · N next pending.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const order = queue?.map((r) => r.image_id) ?? [];
      const i = order.indexOf(id);
      if (e.key === "Escape") go("/");
      else if (e.key === "j" && i >= 0 && i < order.length - 1) go(`/frame/${order[i + 1]}`);
      else if (e.key === "k" && i > 0) go(`/frame/${order[i - 1]}`);
      else if (e.key === " ") setPlaying((p) => (tracks && t >= tracks.window.end ? (setT(tracks.window.start), true) : !p));
      else if (e.key === "a") document.querySelector<HTMLButtonElement>('[data-hot="approve"]')?.click();
      else if (e.key === "e") document.querySelector<HTMLButtonElement>('[data-hot="escalate"]')?.click();
      else if (e.key === "n" && nextPending) go(`/frame/${nextPending.image_id}`);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [id, queue, tracks, t, nextPending]);

  useEffect(() => {
    if (!toast) return;
    const h = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(h);
  }, [toast]);

  // Live run: the six steps stream in (Ajan izi), the evidence updates after step 5, the brief last.
  // On failure the cached evaluation stays on screen.
  const runLive = async () => {
    setLive({ current: null, done: [] });
    setTab("trace");
    // The steps are the point of the live run: bring the Ajan izi tab into view.
    window.setTimeout(() => document.querySelector(".tabs")?.scrollIntoView({ behavior: smooth(), block: "center" }), 50);
    let final: { result: EvaluationResult; decision: Decision | null } | null = null;
    const apply = (ev: LiveEvent) => {
      if (ev.type === "start") setLive((l) => l && { ...l, current: ev.step });
      else if (ev.type === "step") setLive((l) => l && { current: null, done: [...l.done, ev] });
      else if (ev.type === "packet") setPacket(ev.packet);
      else if (ev.type === "result") final = { result: ev.result, decision: ev.decision };
      else if (ev.type === "error") throw new Error(ev.detail);
    };
    // Warm runs finish in ~0,1 s; finished steps are revealed at least STEP_REVEAL_MS apart so the six
    // steps can be followed on screen. Only the reveal is paced: every duration shown is the real one.
    const pending: LiveEvent[] = [];
    let streamEnded = false;
    const player = (async () => {
      let last = 0;
      for (;;) {
        const ev = pending.shift();
        if (!ev) {
          if (streamEnded) return;
          await sleep(20);
          continue;
        }
        if (ev.type === "step") {
          await sleep(Math.max(0, last + STEP_REVEAL_MS - performance.now()));
          last = performance.now();
        }
        apply(ev);
      }
    })();
    player.catch(() => undefined); // awaited below; this only silences it when the stream itself failed first
    try {
      try {
        await api.evaluateStream(id, true, (ev) => void pending.push(ev));
      } finally {
        streamEnded = true;
      }
      await player;
      const f = final as { result: EvaluationResult; decision: Decision | null } | null;
      if (!f) throw new Error("sonuç gelmedi");
      setRes(f.result);
      setPacket(f.result.packet);
      setDecision(f.decision);
      setTracks(await api.tracks(id));
      setToast(`Canlı değerlendirme tamamlandı · ${Math.round(f.result.timings_ms.core + f.result.timings_ms.brief)} ms`);
      onChanged();
    } catch (e) {
      setToast(`Canlı değerlendirme tamamlanamadı; önbellekteki değerlendirme ekranda. ${explain(e)}`);
      if (res) setPacket(res.packet);
    } finally {
      setLive(null);
    }
  };

  const position = queue ? queue.findIndex((r) => r.image_id === id) : -1;

  const retryLLM = async () => {
    const prev = res;
    setRes(null); // skeleton: "Brief hazırlanıyor (LLM)"
    try {
      const f = await api.evaluate(id, false);
      setRes(f.result);
      setDecision(f.decision);
      setToast(f.result.brief_source === "template" ? "LLM'e yine ulaşılamadı; kural tabanlı brief gösteriliyor" : "Brief LLM ile yeniden yazıldı");
      onChanged();
    } catch (e) {
      setRes(prev);
      setToast(`Brief yeniden yazılamadı. ${explain(e)}`);
    }
  };

  // Report chips also show the report's time (R075 · 12:35): the aha is about *when* it was written.
  const refLabels = useMemo(() => Object.fromEntries((packet?.reports ?? []).map((r) => [r.report_id, r.time])), [packet]);
  const focusedReport = focus?.kind === "report" ? packet?.reports.find((r) => r.report_id === focus.id) : undefined;
  const focusedPin = focus?.kind === "report" ? tracks?.report_pins.find((p) => p.report_id === focus.id) : undefined;
  const callout = focusedReport && (
    <ReportCallout
      report={focusedReport}
      atReportTime={!focusedPin || t === focusedPin.t_min}
      onSeek={() => pickReport(focusedReport.report_id)}
      onClose={() => setFocus(null)}
      onRef={onRef}
    />
  );

  return (
    <RefLabels.Provider value={refLabels}>
    <div className="app">
      <TopBar health={health} />
      {error != null && <ErrorState error={error} onRetry={load} />}
      {!packet || !tracks || !mapCtx ? (
        error == null && <Loading label="Kanıt paketi hazırlanıyor" />
      ) : (
        <>
          <div className="frame-bar">
            <FrameHeader
              id={id}
              zone={packet.frame.zone}
              capture={packet.frame.capture_time}
              dist={km(packet.frame.d_base_m)}
              dir={packet.frame.direction}
            />
            <div className="frame-bar-right">
              {position >= 0 && (
                <span className="muted small queue-pos">
                  Kuyrukta {position + 1}/{queue!.length} · <Kbd>J</Kbd>/<Kbd>K</Kbd>
                </span>
              )}
              <button className="btn btn-ghost" onClick={runLive} disabled={!!live} title="Tespit önbelleğini atlayıp 6 adımı yeniden çalıştırır">
                {live ? `Çalışıyor… ${live.done.length}/6` : "↻ Canlı yeniden değerlendir"}
              </button>
              <DecisionBar
                res={res}
                decision={decision}
                onDecision={(d, msg) => {
                  setDecision(d);
                  setToast(msg);
                  onChanged();
                }}
              />
              {decision && nextPending && (
                <button className="btn" onClick={() => go(`/frame/${nextPending.image_id}`)} title="Karar bekleyen sonraki kare (risk sırasıyla)">
                  Sonraki bekleyen → <Kbd>N</Kbd>
                </button>
              )}
            </div>
          </div>
          <main tabIndex={-1} className="frame-grid">
            <div className="col-left">
              <BriefPanel res={res} onRef={onRef} activeRef={activeRef} onRetryLLM={retryLLM} />
              <section className="panel">
                <div className="panel-head">
                  <h2>Görüntü</h2>
                  <span className="muted small">{packet.detector}</span>
                </div>
                <ImagePanel
                  packet={packet}
                  url={api.imageUrl(id)}
                  focusTrack={focus?.kind === "track" ? focus.id : null}
                  levels={tracks.vehicle_levels}
                  onFocusTrack={(tid) => tid && setFocus({ kind: "track", id: tid })}
                />
              </section>
            </div>
            <div className="col-right">
              <section className="panel map-panel">
                <FrameMap
                  ctx={mapCtx}
                  frame={packet.frame}
                  imageUrl={api.imageUrl(id)}
                  data={tracks}
                  t={t}
                  focus={focus}
                  onFocus={(f) => (f?.kind === "report" ? pickReport(f.id) : setFocus(f))}
                />
                <TimeSlider
                  data={tracks}
                  t={t}
                  onChange={(x) => {
                    setPlaying(false);
                    setT(x);
                  }}
                  playing={playing}
                  onPlay={() => {
                    if (t >= tracks.window.end) setT(tracks.window.start);
                    setPlaying((p) => !p);
                  }}
                  focusReport={focus?.kind === "report" ? focus.id : null}
                  onPickReport={pickReport}
                />
                {callout}
              </section>
              <EvidenceTabs
                packet={packet}
                res={res}
                tab={tab}
                setTab={setTab}
                focusReport={focus?.kind === "report" ? focus.id : null}
                onPickReport={pickReport}
                onRef={onRef}
                live={live}
              />
            </div>
          </main>
        </>
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
    </RefLabels.Provider>
  );
}
