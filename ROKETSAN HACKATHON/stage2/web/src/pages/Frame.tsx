import { useCallback, useEffect, useMemo, useState } from "react";
import { go } from "../App";
import { BriefPanel, DecisionBar, FrameHeader } from "../components/Brief";
import { type Focus, FrameMap, TimeSlider } from "../components/FrameMap";
import { ImagePanel } from "../components/ImagePanel";
import { EvidenceTabs, type TabId } from "../components/Tabs";
import { ErrorState, Kbd, Loading, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { km, storage } from "../lib/format";
import type {
  Decision,
  EvaluationResult,
  EvidencePacket,
  FrameTracks,
  Health,
  MapContext,
  TriageRow,
} from "../lib/types";

interface Props {
  id: string;
  health: Health | null;
  queue: TriageRow[] | null;
  onChanged: () => void;
}

export function FramePage({ id, health, queue, onChanged }: Props) {
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [tracks, setTracks] = useState<FrameTracks | null>(null);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [res, setRes] = useState<EvaluationResult | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState<Focus>(null);
  const [tab, setTab] = useState<TabId>("why");
  const [toast, setToast] = useState<string | null>(null);
  const [live, setLive] = useState(false);

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
      .catch((e) => setError(String(e.message ?? e)));
    api
      .frame(id)
      .then((f) => {
        setRes(f.result);
        setPacket(f.result.packet);
        setDecision(f.decision);
        onChanged();
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [id, onChanged]);
  useEffect(load, [load]);

  useEffect(() => {
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

  // Keyboard: Esc back · J/K next/prev frame in the queue · Space play · A approve · E escalate.
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
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [id, queue, tracks, t]);

  useEffect(() => {
    if (!toast) return;
    const h = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(h);
  }, [toast]);

  const runLive = async () => {
    setLive(true);
    try {
      const f = await api.evaluate(id, true);
      setRes(f.result);
      setPacket(f.result.packet);
      setDecision(f.decision);
      setTracks(await api.tracks(id));
      setTab("trace");
      setToast(`Canlı değerlendirme tamamlandı · ${Math.round(f.result.timings_ms.core + f.result.timings_ms.brief)} ms`);
      onChanged();
    } catch (e) {
      setToast(`Canlı değerlendirme başarısız: ${(e as Error).message}`);
    } finally {
      setLive(false);
    }
  };

  const position = queue ? queue.findIndex((r) => r.image_id === id) : -1;

  return (
    <div className="app">
      <TopBar health={health} />
      {error && <ErrorState error={error} onRetry={load} />}
      {!packet || !tracks || !mapCtx ? (
        !error && <Loading label="Kanıt paketi hazırlanıyor" />
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
                <span className="muted small">
                  Kuyrukta {position + 1}/{queue!.length} · <Kbd>J</Kbd>/<Kbd>K</Kbd>
                </span>
              )}
              <button className="btn btn-ghost" onClick={runLive} disabled={live} title="Tespit önbelleğini atlayıp 6 adımı yeniden çalıştırır">
                {live ? "Çalışıyor…" : "↻ Canlı yeniden değerlendir"}
              </button>
              <DecisionBar
                res={res}
                decision={decision}
                onDecision={(d, msg) => {
                  setDecision(d);
                  setToast(msg);
                }}
              />
            </div>
          </div>
          <main className="frame-grid">
            <div className="col-left">
              <BriefPanel res={res} onRef={onRef} activeRef={activeRef} />
              <section className="panel">
                <div className="panel-head">
                  <h2>Görüntü</h2>
                  <span className="muted small">{packet.detector}</span>
                </div>
                <ImagePanel
                  packet={packet}
                  url={api.imageUrl(id)}
                  focusTrack={focus?.kind === "track" ? focus.id : null}
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
              </section>
              <EvidenceTabs
                packet={packet}
                res={res}
                tab={tab}
                setTab={setTab}
                focusReport={focus?.kind === "report" ? focus.id : null}
                onPickReport={pickReport}
                onRef={onRef}
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
  );
}
