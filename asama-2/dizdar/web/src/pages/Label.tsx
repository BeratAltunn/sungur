import { useCallback, useEffect, useMemo, useState } from "react";
import { go } from "../App";
import { type Focus, FrameMap, ReportCallout, TimeSlider } from "../components/FrameMap";
import { ImagePanel } from "../components/ImagePanel";
import { EvidenceTabs, type TabId } from "../components/Tabs";
import { ErrorState, Kbd, Loading, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { LEVELS, LEVEL_ACTION, LEVEL_CLASS, km, storage, zoneName } from "../lib/format";
import type { EvidencePacket, FrameTracks, Health, Level, MapContext } from "../lib/types";

/**
 * Blind gold-set labelling (PROJECT_DESIGN §3.6): the labeler sees the evidence (image, vehicles,
 * 2-hour tracks, verified reports) but never the system's level, score, brief or factors.
 * Frames come in capture-time order, not risk order. Labels go to calibration/labels/<name>.jsonl.
 */
export function LabelPage({ id, health }: { id: string | null; health: Health | null }) {
  const [labeler, setLabeler] = useState<string>(() => storage.get("labeler", ""));
  const [nameInput, setNameInput] = useState(labeler);
  const [order, setOrder] = useState<string[]>([]);
  const [done, setDone] = useState<Record<string, Level>>({});
  const [error, setError] = useState<unknown>(null);

  const loadProgress = useCallback(() => {
    if (!labeler) return;
    api
      .goldProgress(labeler)
      .then((p) => {
        setOrder(p.order);
        setDone(p.done);
      })
      .catch((e) => setError(e));
  }, [labeler]);
  useEffect(loadProgress, [loadProgress]);

  // No frame in the URL: jump to the first unlabelled one.
  useEffect(() => {
    if (!labeler || id || !order.length) return;
    const next = order.find((f) => !done[f]) ?? order[0];
    go(`/label/${next}`);
  }, [labeler, id, order, done]);

  if (!labeler)
    return (
      <div className="app">
        <TopBar health={health} blind />
        <main tabIndex={-1} className="label-intro panel">
          <h1>Kör etiketleme (altın set)</h1>
          <p>
            Her kare için <b>sistemin çıktısını görmeden</b>, yalnızca kanıta bakarak bir risk seviyesi verin: görüntü ve
            araçlar, 2 saatlik hareket izleri, üsse mesafe, raporlar ve doğrulama kararları. Sistemin seviyesi, skoru,
            brief'i ve faktörleri bu ekranda gizlidir; araç renkleri de nötrdür.
          </p>
          <ul>
            {LEVELS.slice()
              .reverse()
              .map((l) => (
                <li key={l}>
                  <span className={`level ${LEVEL_CLASS[l]} level-sm`}>
                    {l}
                  </span>{" "}
                  {LEVEL_ACTION[l]}
                </li>
              ))}
          </ul>
          <p className="muted">
            İki kişi birbirinden bağımsız etiketler; sonuçları konuşmadan önce ikiniz de bitirin. Etiketler{" "}
            <code>calibration/labels/&lt;adınız&gt;.jsonl</code> dosyasına yazılır ve git ile paylaşılır.
          </p>
          <form
            className="label-name"
            onSubmit={(e) => {
              e.preventDefault();
              if (!nameInput.trim()) return;
              storage.set("labeler", nameInput.trim());
              setLabeler(nameInput.trim());
            }}
          >
            <input autoFocus placeholder="Adınız (örn. ayse)" value={nameInput} onChange={(e) => setNameInput(e.target.value)} />
            <button className="btn btn-primary" disabled={!nameInput.trim()}>
              Başla
            </button>
          </form>
        </main>
      </div>
    );

  return (
    <div className="app">
      <TopBar
        blind
        health={health}
        left={
          <span className="pill pill-strong" title="Sistem çıktısı gizli">
            Kör etiketleme · {labeler} · {Object.keys(done).length}/{order.length || "…"}
            <button
              className="linklike"
              onClick={() => {
                storage.set("labeler", "");
                setLabeler("");
              }}
            >
              değiştir
            </button>
          </span>
        }
      />
      {error != null && <ErrorState error={error} onRetry={loadProgress} />}
      {id && (
        <LabelFrame
          key={id}
          id={id}
          labeler={labeler}
          order={order}
          done={done}
          onSaved={(img, lv) => {
            const nextDone = { ...done, [img]: lv };
            setDone(nextDone);
            const i = order.indexOf(img);
            const next = [...order.slice(i + 1), ...order.slice(0, i)].find((f) => !nextDone[f]);
            if (next) go(`/label/${next}`);
          }}
        />
      )}
    </div>
  );
}

function LabelFrame({
  id,
  labeler,
  order,
  done,
  onSaved,
}: {
  id: string;
  labeler: string;
  order: string[];
  done: Record<string, Level>;
  onSaved: (id: string, level: Level) => void;
}) {
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [tracks, setTracks] = useState<FrameTracks | null>(null);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState<Focus>(null);
  const [tab, setTab] = useState<TabId>("vehicles");
  const [level, setLevel] = useState<Level | null>(done[id] ?? null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([api.packet(id), api.tracks(id), api.map()])
      .then(([p, tr, m]) => {
        setPacket(p);
        setTracks(tr);
        setMapCtx(m);
        setT(tr.window.end);
      })
      .catch((e) => setError(e));
  }, [id]);

  useEffect(() => {
    if (!playing || !tracks) return;
    const h = window.setInterval(() => setT((x) => (x >= tracks.window.end ? (setPlaying(false), x) : x + 1)), 90);
    return () => window.clearInterval(h);
  }, [playing, tracks]);

  const save = useCallback(async () => {
    if (!level || saving) return;
    setSaving(true);
    try {
      await api.gold(id, { labeler, level, note });
      onSaved(id, level);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  }, [id, labeler, level, note, onSaved, saving]);

  // 1–4 pick a level (DÜŞÜK→KRİTİK), Enter saves, J/K move in capture order.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Enter" && tag === "INPUT") save();
        return;
      }
      const i = order.indexOf(id);
      if (["1", "2", "3", "4"].includes(e.key)) setLevel(LEVELS[4 - Number(e.key)]);
      else if (e.key === "Enter") save();
      else if (e.key === "j" && i < order.length - 1) go(`/label/${order[i + 1]}`);
      else if (e.key === "k" && i > 0) go(`/label/${order[i - 1]}`);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [id, order, save]);

  const pickReport = (rid: string) => {
    const pin = tracks?.report_pins.find((p) => p.report_id === rid);
    setFocus({ kind: "report", id: rid });
    setTab("reports");
    if (pin) setT(pin.t_min);
  };
  const trackOf = useMemo(() => Object.fromEntries((packet?.vehicles ?? []).map((v) => [v.ref, v.track_id])), [packet]);
  const onRef = (ref: string) => {
    if (ref.startsWith("R")) pickReport(ref);
    else if (ref.startsWith("V")) setFocus(trackOf[ref] ? { kind: "track", id: trackOf[ref]! } : null);
    else setFocus({ kind: "track", id: ref });
  };

  if (error) return <ErrorState error={error} />;
  if (!packet || !tracks || !mapCtx) return <Loading label="Kanıt yükleniyor" />;
  // Report verdicts are evidence the labeller may see (the Reports tab shows them too); no level or score.
  const focusedReport = focus?.kind === "report" ? packet.reports.find((r) => r.report_id === focus.id) : undefined;
  const focusedPin = focus?.kind === "report" ? tracks.report_pins.find((p) => p.report_id === focus.id) : undefined;
  const callout = focusedReport && (
    <ReportCallout
      report={focusedReport}
      atReportTime={!focusedPin || t === focusedPin.t_min}
      onSeek={() => pickReport(focusedReport.report_id)}
      onClose={() => setFocus(null)}
      onRef={onRef}
    />
  );
  const pos = order.indexOf(id);
  const f = packet.frame;

  return (
    <>
      <div className="frame-bar">
        <div className="frame-title">
          <h2 className="mono">{id}</h2>
          <span>
            {zoneName(f.zone)} · {f.capture_time} · üsten {km(f.d_base_m)} {f.direction}
          </span>
          <span className="muted small">
            Kare {pos + 1}/{order.length} (çekim saatine göre) · <Kbd>J</Kbd>/<Kbd>K</Kbd>
          </span>
        </div>
        <form
          className="label-form"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <div className="label-levels" role="radiogroup" aria-label="Sizce seviye">
            {LEVELS.slice()
              .reverse()
              .map((l, i) => (
                <button
                  type="button"
                  key={l}
                  role="radio"
                  aria-checked={level === l}
                  className={`level ${LEVEL_CLASS[l]} level-md ${level === l ? "level-picked" : "level-unpicked"}`}
                  onClick={() => setLevel(l)}
                >
                  {l} <Kbd>{i + 1}</Kbd>
                </button>
              ))}
          </div>
          <input placeholder="Not (isteğe bağlı): neden bu seviye?" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn btn-primary" disabled={!level || saving}>
            {done[id] ? "Güncelle" : "Kaydet"} ve sonraki <Kbd>Enter</Kbd>
          </button>
        </form>
      </div>
      <main tabIndex={-1} className="frame-grid">
        <div className="col-left">
          <section className="panel">
            <div className="panel-head">
              <h2>Görüntü</h2>
            </div>
            <ImagePanel
              blind
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
              blind
              ctx={mapCtx}
              frame={packet.frame}
              imageUrl={api.imageUrl(id)}
              data={tracks}
              t={t}
              focus={focus}
              onFocus={(fc) => (fc?.kind === "report" ? pickReport(fc.id) : setFocus(fc))}
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
            only={["vehicles", "reports"]}
            packet={packet}
            res={null}
            tab={tab}
            setTab={setTab}
            focusReport={focus?.kind === "report" ? focus.id : null}
            onPickReport={pickReport}
            onRef={onRef}
          />
        </div>
      </main>
    </>
  );
}
