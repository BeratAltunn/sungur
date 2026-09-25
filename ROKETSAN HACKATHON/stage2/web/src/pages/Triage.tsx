import type { Map as MLMap, Marker } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { go } from "../App";
import { MapView, fc, htmlMarker, line, setGeo } from "../components/MapView";
import { ReplayBar, useReplay } from "../components/Replay";
import { DecisionPill, ErrorState, Kbd, LevelBadge, Loading, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { LEVELS, LEVEL_ACTION, LEVEL_CLASS, LEVEL_ICON, dec, km, secs, storage, zoneName } from "../lib/format";
import type { Health, Level, MapContext, ShiftSummary, TriageRow } from "../lib/types";

export function TriagePage({ health, queue }: { health: Health | null; queue: TriageRow[] | null }) {
  const [summary, setSummary] = useState<ShiftSummary | null>(null);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zone, setZone] = useState<string>("");
  const [level, setLevel] = useState<Level | "">("");
  const [status, setStatus] = useState<Status>("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [showTip, setShowTip] = useState(() => !storage.get("tip_seen", false));
  const viewed = useMemo(() => new Set(storage.get<string[]>("viewed", [])), []);
  const replay = useReplay();

  const load = () => {
    setError(null);
    Promise.all([api.summary(), api.map()])
      .then(([s, m]) => {
        setSummary(s);
        setMapCtx(m);
      })
      .catch((e) => setError(String(e.message ?? e)));
  };
  useEffect(load, [queue]);

  const rows = useMemo(
    () =>
      (queue ?? []).filter(
        (r) =>
          (!replay.arrived || replay.arrived.has(r.image_id)) &&
          (!search.trim() || r.image_id.includes(search.trim().toLowerCase())) &&
          (!zone || r.zone === zone) &&
          (!level || r.level === level) &&
          (status !== "unseen" || !viewed.has(r.image_id)) &&
          (status !== "pending" || !r.decision) &&
          (status !== "escalated" || r.decision?.action === "escalate"),
      ),
    [queue, zone, level, status, viewed, search, replay.arrived],
  );
  useEffect(() => setCursor(0), [zone, level, status, search]);

  // J/K move, Enter opens: the queue is operated from the keyboard.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "SELECT" || (tag === "INPUT" && e.key !== "Enter" && e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
      if (e.key === "j" || e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, rows.length - 1));
      else if (e.key === "k" || e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
      else if (e.key === "Enter" && rows[cursor]) go(`/frame/${rows[cursor].image_id}`);
      else if (e.key === " " && replay.state && tag !== "INPUT") replay.set({ playing: !replay.state.playing });
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [rows, cursor, replay]);

  // Roving focus: the queue is one Tab stop; J/K (or ↑/↓) move the cursor and, if a row has focus, the focus too.
  useEffect(() => {
    const el = document.querySelector<HTMLElement>(`[data-row="${cursor}"]`);
    el?.scrollIntoView({ block: "nearest" });
    if (document.activeElement?.classList.contains("row")) el?.focus();
  }, [cursor]);

  const zones = useMemo(() => [...new Set((queue ?? []).map((r) => r.zone))].sort(), [queue]);

  return (
    <div className="app">
      <TopBar health={health} />
      {error && <ErrorState error={error} onRetry={load} />}
      {replay.state ? <ReplayBar r={replay} /> : summary && <ShiftCard summary={summary} queue={queue} />}
      {showTip && (
        <div className="tip" role="note">
          <span>
            <strong>Nasıl kullanılır:</strong> 1. Kuyruk en riskli kareden başlar; ETA sütunu en yakın varışı gösterir · 2.
            Kareyi açınca önce brief, altında kanıt gelir · 3. <em>Neden?</em> sekmesi puanın nereden geldiğini gösterir.
            Bir rapora tıklayınca harita o saate gider. Karar verince <Kbd>N</Kbd> ile sonraki bekleyen kareye geçin.
          </span>
          <button
            className="btn btn-ghost"
            onClick={() => {
              storage.set("tip_seen", true);
              setShowTip(false);
            }}
          >
            Anladım
          </button>
        </div>
      )}

      <main tabIndex={-1} className="triage">
        <section className="queue panel" aria-label="Risk kuyruğu">
          <div className="panel-head">
            <h2>
              Kuyruk {replay.arrived && <span className="muted small">· {rows.length} kare geldi</span>}
            </h2>
            {!replay.state && (
              <button className="btn btn-ghost btn-sm" onClick={replay.start} title="Günü simüle saatle oynat: kareler çekim saatinde kuyruğa düşer">
                ▶ Vardiyayı oynat
              </button>
            )}
            <div className="filters">
              <input
                className="search"
                type="search"
                placeholder="Kare no: 6388"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Kare ara"
              />
              <select value={zone} onChange={(e) => setZone(e.target.value)} aria-label="Bölge">
                <option value="">Tüm bölgeler</option>
                {zones.map((z) => (
                  <option key={z} value={z}>
                    {zoneName(z)}
                  </option>
                ))}
              </select>
              <select value={level} onChange={(e) => setLevel(e.target.value as Level | "")} aria-label="Seviye">
                <option value="">Tüm seviyeler</option>
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {LEVEL_ICON[l]} {l}
                  </option>
                ))}
              </select>
              <select value={status} onChange={(e) => setStatus(e.target.value as Status)} aria-label="Durum">
                <option value="">Tüm durumlar</option>
                <option value="pending">Karar bekleyenler</option>
                <option value="unseen">Bakılmamışlar</option>
                <option value="escalated">Amire iletilenler</option>
              </select>
            </div>
          </div>
          {!queue ? (
            <Loading label="Kareler değerlendiriliyor" />
          ) : rows.length === 0 ? (
            <div className="state">Bu filtreyle eşleşen kare yok.</div>
          ) : (
            <ol className="rows">
              {rows.map((r, i) => (
                <li
                  key={r.image_id}
                  data-row={i}
                  className={`row ${i === cursor ? "row-cursor" : ""} ${viewed.has(r.image_id) ? "row-seen" : ""}`}
                  onClick={() => go(`/frame/${r.image_id}`)}
                  tabIndex={i === cursor ? 0 : -1}
                  onFocus={() => setCursor(i)}
                  aria-label={`${r.level}, ${r.image_id}, ${zoneName(r.zone)}, ${r.capture_time}, üsse ${km(r.d_base_m)}, ${r.min_eta_min === null ? "yaklaşan yok" : `ETA yaklaşık ${dec(r.min_eta_min)} dakika`}${r.reports_contradicted ? `, ${r.reports_contradicted} rapor çelişiyor` : ""}${r.decision ? ", karar verildi" : ""}. ${r.headline}`}
                  onMouseEnter={() => setHover(r.image_id)}
                  onMouseLeave={() => setHover(null)}
                >
                  <div className="row-level">
                    <LevelBadge level={r.level} size="sm" />
                    {r.decision && <DecisionPill decision={r.decision} />}
                  </div>
                  <div className="row-main">
                    <div className="row-top">
                      <span className="mono">{r.capture_time}</span>
                      <span className="row-zone">{zoneName(r.zone)}</span>
                      <span className="mono" title="Kare merkezinin üsse mesafesi">
                        {km(r.d_base_m)}
                      </span>
                      <span
                        className={`mono row-eta ${r.min_eta_min === null ? "muted" : ""}`}
                        title="Üsse yaklaşan araçlar arasında en kısa varış süresi"
                      >
                        {r.min_eta_min === null ? "yaklaşan yok" : `ETA ~${dec(r.min_eta_min)} dk`}
                      </span>
                    </div>
                    <div className="row-sub">
                      <span className="row-headline" title={r.headline}>
                        <span className="mono muted">{r.image_id}</span> {r.headline}
                      </span>
                      <span className="row-tags">
                        {r.n_approaching > 0 && (
                          <span className="tag" title={`${r.n_approaching} araç üsse yaklaşıyor`}>
                            ⇢{r.n_approaching} yaklaşan
                          </span>
                        )}
                        {r.n_heavy > 0 && (
                          <span className="tag" title="Kamyon / otobüs">
                            {r.n_heavy} ağır
                          </span>
                        )}
                        {r.reports_contradicted > 0 && (
                          <span className="verdict vd-bad" title="Kanıtla çelişen rapor">
                            ✗{r.reports_contradicted}
                          </span>
                        )}
                        {replay.arrived && replay.isNew(r.image_id) && <span className="tag tag-new">YENİ</span>}
                        {!viewed.has(r.image_id) && <span className="unseen" title="Bakılmadı" />}
                      </span>
                    </div>
                  </div>
                  <span className="score mono" title="Risk skoru">
                    {r.score}
                  </span>
                </li>
              ))}
            </ol>
          )}
          <div className="hint">
            <Kbd>J</Kbd>/<Kbd>K</Kbd> gez · <Kbd>Enter</Kbd> aç
          </div>
        </section>

        <section className="panel overview" aria-label="Bölge haritası">
          <div className="panel-head">
            <h2>Bölge haritası</h2>
            <span className="muted">Üs merkezde · halkalar {mapCtx?.rings.map((r) => `${r.km} km`).join(" / ")}</span>
          </div>
          {mapCtx ? <OverviewMap ctx={mapCtx} hover={hover} visible={replay.arrived} /> : <Loading />}
          <Legend />
        </section>
      </main>
    </div>
  );
}

type Status = "" | "pending" | "unseen" | "escalated";

/** Measured in the product (decision log + frame openings), not assumed: see PROJECT_DESIGN §1.4, §1.6. */
export function DecisionMetrics({ summary: s }: { summary: ShiftSummary }) {
  return (
    <span className="metrics">
      <span title="Kare açılışından operatör kararına kadar geçen süre (medyan). Tasarım varsayımı: elle ~6 dk/kare.">
        Karar süresi:{" "}
        {s.decision_median_s === null ? (
          <span className="muted">henüz ölçüm yok</span>
        ) : (
          <>
            <strong>{secs(s.decision_median_s)}</strong> <span className="muted">medyan · {s.decision_timed} karar</span>
          </>
        )}
      </span>
      {s.high_decided > 0 && (
        <span title="Yanlış alarm göstergesi: operatörün seviyesini düşürdüğü YÜKSEK/KRİTİK kareler">
          Seviye düşürme: <strong>{s.high_downgraded}/{s.high_decided}</strong>
        </span>
      )}
    </span>
  );
}

function ShiftCard({ summary, queue }: { summary: ShiftSummary; queue: TriageRow[] | null }) {
  const u = summary.most_urgent;
  // The next YÜKSEK/KRİTİK frame still waiting for the operator (queue order = risk order).
  const next = queue?.find((r) => !r.decision && (r.level === "KRİTİK" || r.level === "YÜKSEK"));
  return (
    <section className="shift" aria-label="Nöbet devri">
      <div className="shift-stats">
        <span className="shift-title">Nöbet devri</span>
        <span>
          <strong>{summary.frames}</strong> kare · <strong>{summary.reports}</strong> rapor işlendi
        </span>
        <span className="shift-levels">
          {LEVELS.map((l) => (
            <span key={l} className={`level ${LEVEL_CLASS[l]} level-sm`}>
              {LEVEL_ICON[l]} {l} {summary.by_level[l] ?? 0}
            </span>
          ))}
        </span>
        <span className="muted">
          {summary.contradicted_reports} rapor çelişiyor · {summary.decided} karar verildi ·{" "}
          <strong className={summary.awaiting_high ? "warn-text" : ""}>{summary.awaiting_high} YÜKSEK/KRİTİK karar bekliyor</strong>
        </span>
        <DecisionMetrics summary={summary} />
        <a className="btn btn-ghost btn-sm shift-handover" href="#/handover" title="Amir için kurala dayalı vardiya özeti (yazdırılabilir)">
          Vardiya devri özeti →
        </a>
        <a className="btn btn-ghost btn-sm" href="#/impact" title="Vardiya simülasyonu: karar, araçlar üsse varmadan önce mi?">
          Etki →
        </a>
      </div>
      {u && (
        <div className="shift-urgent">
          <span className="muted">En acil</span>
          <LevelBadge level={u.level} size="sm" />
          <span className="mono">{u.image_id}</span>
          <span>
            {zoneName(u.zone)} · {u.capture_time}
          </span>
          <span className="shift-headline">“{u.headline}”</span>
          {u.decision ? <DecisionPill decision={u.decision} /> : <span className="muted">{LEVEL_ACTION[u.level]}</span>}
          <button className="btn btn-primary" onClick={() => go(`/frame/${u.image_id}`)}>
            Kareyi aç →
          </button>
          {u.decision && next && (
            <button className="btn" onClick={() => go(`/frame/${next.image_id}`)} title="Karar bekleyen en riskli kare">
              Sonraki bekleyen: {next.image_id} →
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function OverviewMap({ ctx, hover, visible }: { ctx: MapContext; hover: string | null; visible: Set<string> | null }) {
  const markers = useRef<Record<string, Marker>>({});
  const onReady = (map: MLMap) => {
    Object.values(markers.current).forEach((m) => m.remove());
    markers.current = {};
    setGeo(map, "rings", fc(ctx.rings.map((r) => line(r.ring, { km: r.km }))));
    if (!map.getLayer("rings"))
      map.addLayer({
        id: "rings",
        type: "line",
        source: "rings",
        paint: { "line-color": "#3b4656", "line-width": 1, "line-dasharray": [3, 3] },
      });
    htmlMarker(map, ctx.base.center, `<span>◆</span><b>${ctx.base.name}</b>`, "mk mk-base");
    for (const z of ctx.zones) htmlMarker(map, z.center, z.label, "mk mk-zone");
    for (const f of ctx.frames) {
      markers.current[f.image_id] = htmlMarker(
        map,
        f.center,
        `<span class="mk-frame-icon">${LEVEL_ICON[f.level]}</span>`,
        `mk mk-frame ${LEVEL_CLASS[f.level]}`,
        () => go(`/frame/${f.image_id}`),
      );
      markers.current[f.image_id].getElement().title = `${f.image_id} · ${zoneName(f.zone)} · ${f.capture_time} · ${f.level}`;
    }
  };
  useEffect(() => {
    for (const [id, m] of Object.entries(markers.current)) m.getElement().classList.toggle("mk-hover", id === hover);
  }, [hover]);
  // Replay: only frames that have arrived by the simulated clock.
  useEffect(() => {
    for (const [id, m] of Object.entries(markers.current)) m.getElement().style.display = !visible || visible.has(id) ? "" : "none";
  }, [visible]);
  return <MapView className="overview-map" onReady={onReady} initial={{ center: ctx.base.center, zoom: 11.6 }} />;
}

function Legend() {
  return (
    <div className="legend">
      {LEVELS.map((l) => (
        <span key={l} className={`level ${LEVEL_CLASS[l]} level-sm`}>
          {LEVEL_ICON[l]} {l}: {LEVEL_ACTION[l]}
        </span>
      ))}
    </div>
  );
}
