import type { Map as MLMap, Marker } from "maplibre-gl";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { go } from "../App";
import { MapView, fc, htmlMarker, line, setGeo } from "../components/MapView";
import { baseSymbol } from "../lib/symbols";
import { ReplayBar, useReplay } from "../components/Replay";
import { DecisionPill, ErrorState, Kbd, LevelBadge, Loading, SummaryContext, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { LEVELS, LEVEL_ACTION, LEVEL_CLASS, LEVEL_COLOR, LEVEL_ICON, dec, km, secs, storage, zoneName } from "../lib/format";
import type { Health, Level, MapContext, ShiftSummary, TriageRow } from "../lib/types";

export function TriagePage({ health, queue }: { health: Health | null; queue: TriageRow[] | null }) {
  const summary = useContext(SummaryContext);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [error, setError] = useState<unknown>(null);
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
    api
      .map()
      .then(setMapCtx)
      .catch((e) => setError(e));
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
  const decided = useMemo(() => new Set((queue ?? []).filter((r) => r.decision).map((r) => r.image_id)), [queue]);

  const selected = rows[cursor] ?? null;

  return (
    <div className="app">
      <TopBar health={health} />
      {error != null && <ErrorState error={error} onRetry={load} />}
      {replay.state ? (
        <ReplayBar r={replay} />
      ) : (
        summary && <ShiftStrip summary={summary} onReplay={replay.start} />
      )}
      {showTip && (
        <div className="tip" role="note">
          <span>
            <strong>Nasıl kullanılır:</strong> Solda uyarılar risk sırasıyla; tıklayınca sağda önizleme açılır, <Kbd>Enter</Kbd>{" "}
            kareyi açar. Karede önce brief, altında kanıt gelir; <em>Neden?</em> puanın kaynağını gösterir. Karar verince{" "}
            <Kbd>N</Kbd> sonraki bekleyen kareye geçer.
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

      {/* Common operational picture: alerts (left) · map (centre) · selected frame (right). */}
      <main tabIndex={-1} className="triage cop">
        <section className="queue panel" aria-label="Uyarılar">
          <div className="panel-head">
            <h2>
              Uyarılar{" "}
              <span className="muted small">
                · {rows.length}
                {replay.arrived ? " kare geldi" : " kare"}
              </span>
            </h2>
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
                  onClick={() => setCursor(i)}
                  onDoubleClick={() => go(`/frame/${r.image_id}`)}
                  tabIndex={i === cursor ? 0 : -1}
                  onFocus={() => setCursor(i)}
                  aria-selected={i === cursor}
                  aria-label={`${r.level}, ${r.image_id}, ${zoneName(r.zone)}, ${r.capture_time}, üsse ${km(r.d_base_m)}, ${r.min_eta_min === null ? "yaklaşan yok" : `ETA yaklaşık ${dec(r.min_eta_min)} dakika`}${r.reports_contradicted ? `, ${r.reports_contradicted} rapor çelişiyor` : ""}${r.decision ? ", karar verildi" : ""}. ${r.headline}`}
                  onMouseEnter={() => setHover(r.image_id)}
                  onMouseLeave={() => setHover(null)}
                >
                  <div className="row-level">
                    <LevelBadge level={r.level} size="sm" tone={r.decision ? "quiet" : "auto"} />
                    {r.decision && <DecisionPill decision={r.decision} />}
                  </div>
                  <div className="row-main">
                    <div className="row-top">
                      <span className="mono">{r.capture_time}</span>
                      <span className="row-zone">{zoneName(r.zone)}</span>
                      <span
                        className={`mono row-eta ${r.min_eta_min === null ? "muted" : ""}`}
                        title="Üsse yaklaşan araçlar arasında en kısa varış süresi"
                      >
                        {r.min_eta_min === null ? "yaklaşan yok" : `ETA ~${dec(r.min_eta_min)} dk`}
                      </span>
                    </div>
                    <div className="row-sub">
                      <span className="mono muted">{r.image_id}</span>
                      <span className="mono muted" title="Kare merkezinin üsse mesafesi">
                        {km(r.d_base_m)}
                      </span>
                      <span className="row-tags">
                        {r.n_approaching > 0 && (
                          <span className="tag" title={`${r.n_approaching} araç üsse yaklaşıyor`}>
                            ⇢{r.n_approaching}
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
            <Kbd>J</Kbd>/<Kbd>K</Kbd> seç · <Kbd>Enter</Kbd> aç · çift tıklama aç
          </div>
        </section>

        <section className="panel overview" aria-label="Bölge haritası">
          <div className="panel-head">
            <h2>Bölge haritası</h2>
            <span className="muted small">Üs merkezde · halkalar {mapCtx?.rings.map((r) => `${r.km} km`).join(" / ")}</span>
          </div>
          {mapCtx ? (
            <OverviewMap
              ctx={mapCtx}
              hover={hover}
              selected={selected?.image_id ?? null}
              visible={replay.arrived}
              decided={decided}
              onSelect={(id) => {
                const i = rows.findIndex((r) => r.image_id === id);
                if (i >= 0) setCursor(i);
              }}
            />
          ) : (
            <Loading />
          )}
          <Legend />
        </section>

        <Preview row={selected} />
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

/** Shift strip: counts, measured decision metrics and the duty-officer links (the most urgent frame is the
 *  default selection of the alert list, shown in the preview panel). */
function ShiftStrip({ summary, onReplay }: { summary: ShiftSummary; onReplay: () => void }) {
  return (
    <section className="shift" aria-label="Nöbet devri">
      <div className="shift-stats">
        <span className="shift-title">Nöbet devri</span>
        <span>
          <strong>{summary.frames}</strong> kare · <strong>{summary.reports}</strong> rapor
        </span>
        <span className="shift-levels">
          {LEVELS.map((l) => (
            <span key={l} className={`level ${LEVEL_CLASS[l]} level-sm`}>
              {LEVEL_ICON[l]} {l} {summary.by_level[l] ?? 0}
            </span>
          ))}
        </span>
        <span className="muted">
          {summary.contradicted_reports} rapor çelişiyor · {summary.decided} karar ·{" "}
          <strong className={summary.awaiting_high ? "warn-text" : ""}>{summary.awaiting_high} YÜKSEK/KRİTİK karar bekliyor</strong>
        </span>
        <DecisionMetrics summary={summary} />
        <span className="shift-links">
          <button className="btn btn-ghost btn-sm" onClick={onReplay} title="Günü simüle saatle oynat: kareler çekim saatinde kuyruğa düşer">
            ▶ Vardiyayı oynat
          </button>
          <a className="btn btn-ghost btn-sm" href="#/handover" title="Amir için kurala dayalı vardiya özeti (yazdırılabilir)">
            Vardiya devri özeti →
          </a>
          <a className="btn btn-ghost btn-sm" href="#/impact" title="Vardiya simülasyonu: karar, araçlar üsse varmadan önce mi?">
            Etki →
          </a>
        </span>
      </div>
    </section>
  );
}

/** Selected alert, without opening it: what the queue row knows (all from the backend) + a thumbnail. */
function Preview({ row: r }: { row: TriageRow | null }) {
  if (!r)
    return (
      <aside className="panel preview" aria-label="Seçili kare">
        <div className="state">Soldan bir uyarı seçin.</div>
      </aside>
    );
  return (
    <aside className="panel preview" aria-label="Seçili kare">
      <div className="panel-head">
        <h2>Seçili kare</h2>
        <span className="mono muted small">skor {r.score}</span>
      </div>
      <div className="preview-body">
        <div className="preview-head">
          <LevelBadge level={r.level} tone={r.decision ? "quiet" : "auto"} />
          {r.decision && <DecisionPill decision={r.decision} />}
        </div>
        <div className="preview-id">
          <span className="mono">{r.image_id}</span>
          <span className="muted">
            {zoneName(r.zone)} · {r.capture_time} · üsten {km(r.d_base_m)}
          </span>
        </div>
        <button className="btn btn-primary preview-open" onClick={() => go(`/frame/${r.image_id}`)}>
          Kareyi aç → <Kbd>Enter</Kbd>
        </button>
        <p className="preview-headline">{r.headline}</p>
        <div className="action" role="note" style={{ ["--act" as string]: LEVEL_COLOR[r.level] }}>
          <span className="action-label">Seviye eylemi</span>
          {LEVEL_ACTION[r.level]}
        </div>
        <dl className="facts">
          <dt>En kısa ETA</dt>
          <dd className="mono">{r.min_eta_min === null ? "yaklaşan yok" : `~${dec(r.min_eta_min)} dk`}</dd>
          <dt>Araç</dt>
          <dd>
            {r.n_vehicles} · {r.n_approaching} yaklaşan · {r.n_heavy} ağır
          </dd>
          <dt>Raporlar</dt>
          <dd>
            <span className="verdict vd-ok">✓{r.reports_confirmed}</span>{" "}
            <span className="verdict vd-bad">✗{r.reports_contradicted}</span>
          </dd>
        </dl>
        <img className="preview-img" src={api.imageUrl(r.image_id)} alt={`${r.image_id} drone karesi (önizleme)`} loading="lazy" />
      </div>
    </aside>
  );
}

function OverviewMap({
  ctx,
  hover,
  selected,
  visible,
  decided,
  onSelect,
}: {
  ctx: MapContext;
  hover: string | null;
  selected: string | null;
  visible: Set<string> | null;
  decided: Set<string>;
  onSelect: (imageId: string) => void;
}) {
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const markers = useRef<Record<string, Marker>>({});
  const [ready, setReady] = useState(0); // markers exist only after the map loads
  const onReady = (map: MLMap) => {
    Object.values(markers.current).forEach((m) => m.remove());
    markers.current = {};
    setGeo(map, "rings", fc(ctx.rings.map((r) => line(r.ring, { km: r.km }))));
    if (!map.getLayer("rings"))
      map.addLayer({
        id: "rings",
        type: "line",
        source: "rings",
        paint: { "line-color": "#3a5775", "line-width": 1, "line-dasharray": [3, 3] },
      });
    htmlMarker(map, ctx.base.center, baseSymbol(ctx.base.name), "mk mk-base");
    for (const z of ctx.zones) htmlMarker(map, z.center, z.label, "mk mk-zone");
    for (const f of ctx.frames) {
      markers.current[f.image_id] = htmlMarker(
        map,
        f.center,
        `<span class="mk-frame-icon">${LEVEL_ICON[f.level]}</span>`,
        `mk mk-frame ${LEVEL_CLASS[f.level]}`,
        () => onSelectRef.current(f.image_id), // select (preview); double-click opens
      );
      markers.current[f.image_id].getElement().addEventListener("dblclick", () => go(`/frame/${f.image_id}`));
      markers.current[f.image_id].getElement().title = `${f.image_id} · ${zoneName(f.zone)} · ${f.capture_time} · ${f.level}`;
    }
    setReady((r) => r + 1);
  };
  useEffect(() => {
    for (const [id, m] of Object.entries(markers.current)) {
      m.getElement().classList.toggle("mk-hover", id === hover);
      m.getElement().classList.toggle("mk-selected", id === selected);
    }
  }, [hover, selected, ready]);
  // Visual quiet: undecided KRİTİK frames are filled; decided ones recede.
  useEffect(() => {
    for (const f of ctx.frames) {
      const el = markers.current[f.image_id]?.getElement();
      if (!el) continue;
      const done = decided.has(f.image_id);
      el.classList.toggle("mk-quiet", done);
      el.classList.toggle("mk-attn", !done && f.level === "KRİTİK");
    }
  }, [decided, ctx, ready]);
  // Replay: only frames that have arrived by the simulated clock.
  useEffect(() => {
    for (const [id, m] of Object.entries(markers.current)) m.getElement().style.display = !visible || visible.has(id) ? "" : "none";
  }, [visible, ready]);
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
