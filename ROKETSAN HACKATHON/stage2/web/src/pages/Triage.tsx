import type { Map as MLMap, Marker } from "maplibre-gl";
import { Fragment, useContext, useEffect, useMemo, useRef, useState } from "react";
import { go } from "../App";
import { LayerMenu, useLayers } from "../components/LayerMenu";
import { MapView, fc, htmlMarker, line, setGeo } from "../components/MapView";
import { LEVEL_LEGEND, VERDICT_LEGEND, baseSymbol } from "../lib/symbols";
import { ReplayBar, useReplay } from "../components/Replay";
import { AnomalyChips } from "../components/VehicleChip";
import { DecisionPill, ErrorState, Kbd, LevelBadge, Loading, SummaryContext, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { LEVELS, LEVEL_ACTION, LEVEL_CLASS, LEVEL_ICON, dec, km, secs, storage, zoneName } from "../lib/format";
import { LEVEL_VAR, token } from "../lib/theme";
import type { EvidencePacket, Health, Level, MapContext, ShiftSummary, TriageRow } from "../lib/types";

/** An active alert: YÜKSEK/KRİTİK with no operator decision yet. These are the cards on top of the rail. */
const isAlert = (r: TriageRow) => !r.decision && (r.level === "KRİTİK" || r.level === "YÜKSEK");
const eta = (r: TriageRow) => (r.min_eta_min === null ? "yaklaşan yok" : `ETA ~${dec(r.min_eta_min)} dk`);

export function TriagePage({
  health,
  queue,
  onSelect,
}: {
  health: Health | null;
  queue: TriageRow[] | null;
  /** The selected frame is the chat's context on this screen. */
  onSelect?: (imageId: string | null) => void;
}) {
  const summary = useContext(SummaryContext);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [zone, setZone] = useState<string>("");
  const [level, setLevel] = useState<Level | "">("");
  const [status, setStatus] = useState<Status>("");
  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(false);
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

  // Two layers in one list: active alerts first (backend risk order), then every other frame (same order).
  const rows = useMemo(() => {
    const shown = (queue ?? []).filter(
      (r) =>
        (!replay.arrived || replay.arrived.has(r.image_id)) &&
        (!search.trim() || r.image_id.includes(search.trim().toLowerCase())) &&
        (!zone || r.zone === zone) &&
        (!level || r.level === level) &&
        (status !== "unseen" || !viewed.has(r.image_id)) &&
        (status !== "pending" || !r.decision) &&
        (status !== "escalated" || r.decision?.action === "escalate"),
    );
    return [...shown.filter(isAlert), ...shown.filter((r) => !isAlert(r))];
  }, [queue, zone, level, status, viewed, search, replay.arrived]);
  const nAlerts = useMemo(() => rows.filter(isAlert).length, [rows]);
  useEffect(() => setCursor(0), [zone, level, status, search]);

  // J/K move, Enter opens: the queue is operated from the keyboard.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "SELECT" || (tag === "INPUT" && e.key !== "Enter" && e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
      if (e.key === "j" || e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, rows.length - 1));
      else if (e.key === "k" || e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
      // The cursor is reset to 0 one render after a filter change; clamp so a fast Enter still opens the row shown.
      else if (e.key === "Enter" && rows.length) go(`/frame/${rows[Math.min(cursor, rows.length - 1)].image_id}`);
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
  const alerts = useMemo(() => new Set((queue ?? []).filter(isAlert).map((r) => r.image_id)), [queue]);
  const nFilters = [zone, level, status].filter(Boolean).length;

  const selected = rows[cursor] ?? null;
  useEffect(() => onSelect?.(selected?.image_id ?? null), [selected?.image_id, onSelect]);
  useEffect(() => () => onSelect?.(null), [onSelect]);

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
            <strong>Nasıl kullanılır:</strong> Solda karar bekleyen uyarılar kart olarak en üstte, diğer kareler altında.
            Seçince sağda özeti açılır, <Kbd>Enter</Kbd> kareyi açar. Karar verince <Kbd>N</Kbd> sonraki bekleyene geçer.
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

      {/* Layers: alerts rail (what to act on) · map (where) · focus card (the selected frame, in brief). */}
      <main tabIndex={-1} className="triage cop">
        <section className="queue panel" aria-label="Uyarılar">
          <div className="panel-head">
            <h2>
              Aktif uyarılar{" "}
              <span className="muted small">
                · {nAlerts} karar bekliyor
                {replay.arrived ? ` · ${rows.length} kare geldi` : ""}
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
              <button className="btn btn-ghost btn-sm" aria-expanded={showFilters} onClick={() => setShowFilters((s) => !s)}>
                Filtre{nFilters ? ` · ${nFilters}` : ""}
              </button>
            </div>
            {showFilters && (
              <div className="filters filters-more">
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
            )}
          </div>
          {!queue ? (
            <Loading label="Kareler değerlendiriliyor" />
          ) : rows.length === 0 ? (
            <div className="state">Bu filtreyle eşleşen kare yok.</div>
          ) : (
            <ol className="rows">
              {nAlerts === 0 && (
                <li className="rows-divider" role="presentation">
                  Karar bekleyen YÜKSEK/KRİTİK uyarı yok
                </li>
              )}
              {rows.map((r, i) => (
                <Fragment key={r.image_id}>
                  {i === nAlerts && nAlerts > 0 && (
                    <li className="rows-divider" role="presentation">
                      Diğer kareler · {rows.length - nAlerts}
                    </li>
                  )}
                  <li
                    data-row={i}
                    className={`row ${i < nAlerts ? `row-card ${r.level === "KRİTİK" ? "row-card-crit" : ""}` : "row-compact"} ${i === cursor ? "row-cursor" : ""} ${viewed.has(r.image_id) ? "row-seen" : ""}`}
                    onClick={() => setCursor(i)}
                    onDoubleClick={() => go(`/frame/${r.image_id}`)}
                    tabIndex={i === cursor ? 0 : -1}
                    onFocus={() => setCursor(i)}
                    aria-selected={i === cursor}
                    aria-label={`${r.level}, ${r.image_id}, ${zoneName(r.zone)}, ${r.capture_time}, üsse ${km(r.d_base_m)}, ${r.min_eta_min === null ? "yaklaşan yok" : `ETA yaklaşık ${dec(r.min_eta_min)} dakika`}${r.reports_contradicted ? `, ${r.reports_contradicted} rapor çelişiyor` : ""}${r.decision ? ", karar verildi" : ""}. ${r.headline}`}
                    onMouseEnter={() => setHover(r.image_id)}
                    onMouseLeave={() => setHover(null)}
                  >
                    {i < nAlerts ? (
                      <AlertCard r={r} isNew={!!replay.arrived && replay.isNew(r.image_id)} seen={viewed.has(r.image_id)} active={i === cursor} />
                    ) : (
                      <CompactRow r={r} isNew={!!replay.arrived && replay.isNew(r.image_id)} />
                    )}
                  </li>
                </Fragment>
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
              alerts={alerts}
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

/** Active alert: level and ETA first (the two facts that decide "now or later"), then where and what. */
function AlertCard({ r, isNew, seen, active }: { r: TriageRow; isNew: boolean; seen: boolean; active: boolean }) {
  return (
    <div className="card-body">
      <div className="card-top">
        <LevelBadge level={r.level} size={r.level === "KRİTİK" ? "md" : "sm"} />
        <span className={`mono card-eta ${r.min_eta_min === null ? "muted" : ""}`} title="Üsse yaklaşan araçlar arasında en kısa varış süresi">
          {eta(r)}
        </span>
        {!seen && <span className="unseen" title="Bakılmadı" />}
      </div>
      <div className="row-sub">
        <span className="mono">{r.image_id}</span>
        <span className="muted">
          {zoneName(r.zone)} · {r.capture_time} · {km(r.d_base_m)}
        </span>
      </div>
      <p className="card-headline">{r.headline}</p>
      <div className="card-foot">
        <span className="row-tags">
          {r.n_approaching > 0 && <span className="tag">{r.n_approaching} yaklaşan</span>}
          {r.n_heavy > 0 && <span className="tag">{r.n_heavy} ağır</span>}
          {r.reports_contradicted > 0 && (
            <span className="verdict vd-bad" title="Kanıtla çelişen rapor">
              ✗{r.reports_contradicted}
            </span>
          )}
          {isNew && <span className="tag tag-new">YENİ</span>}
        </span>
        {active && (
          <button className="btn btn-primary btn-sm" onClick={() => go(`/frame/${r.image_id}`)}>
            Aç → <Kbd>Enter</Kbd>
          </button>
        )}
      </div>
    </div>
  );
}

/** Everything else: one line, the decision (if any) instead of details. */
function CompactRow({ r, isNew }: { r: TriageRow; isNew: boolean }) {
  return (
    <>
      <div className="row-level">
        <LevelBadge level={r.level} size="sm" tone={r.decision ? "quiet" : "outline"} />
      </div>
      <div className="row-main">
        <div className="row-top">
          <span className="mono">{r.capture_time}</span>
          <span className="row-zone">{zoneName(r.zone)}</span>
          <span className={`mono row-eta ${r.min_eta_min === null ? "muted" : ""}`}>{eta(r)}</span>
        </div>
        <div className="row-sub">
          <span className="mono muted">{r.image_id}</span>
          {r.decision && <DecisionPill decision={r.decision} />}
          {isNew && <span className="tag tag-new">YENİ</span>}
        </div>
      </div>
    </>
  );
}

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

/** Shift line: the one number that matters (pending YÜKSEK/KRİTİK) up front; the rest behind "Ayrıntı". */
function ShiftStrip({ summary, onReplay }: { summary: ShiftSummary; onReplay: () => void }) {
  return (
    <section className="shift" aria-label="Nöbet devri">
      <div className="shift-stats">
        <span className="shift-title">Nöbet</span>
        <strong className={summary.awaiting_high ? "attn-text" : ""}>{summary.awaiting_high} YÜKSEK/KRİTİK karar bekliyor</strong>
        <span className="shift-levels">
          {LEVELS.map((l) => (
            <span key={l} className={`level ${LEVEL_CLASS[l]} level-sm`}>
              {LEVEL_ICON[l]} {l} {summary.by_level[l] ?? 0}
            </span>
          ))}
        </span>
        <details className="shift-more">
          <summary>Ayrıntı</summary>
          <div className="shift-more-body">
            <span>
              <strong>{summary.frames}</strong> kare · <strong>{summary.reports}</strong> rapor · {summary.contradicted_reports} rapor
              çelişiyor · {summary.decided} karar
            </span>
            <DecisionMetrics summary={summary} />
          </div>
        </details>
        <span className="shift-links">
          <button className="btn btn-ghost btn-sm" onClick={onReplay} title="Günü simüle saatle oynat: kareler çekim saatinde kuyruğa düşer">
            Vardiyayı oynat
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

/** Focus card: the selected frame in brief (headline, action, three facts); the frame page has the evidence. */
function Preview({ row: r }: { row: TriageRow | null }) {
  const packet = usePacket(r?.image_id ?? null);
  if (!r)
    return (
      <aside className="panel preview" aria-label="Seçili kare">
        <div className="state">Soldan bir uyarı seçin.</div>
      </aside>
    );
  return (
    <aside className="panel preview" aria-label="Seçili kare">
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
        <p className="preview-headline">{r.headline}</p>
        <div className="action" role="note" style={{ ["--act" as string]: `var(${LEVEL_VAR[r.level]})` }}>
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
        <button className="btn btn-primary preview-open" onClick={() => go(`/frame/${r.image_id}`)}>
          Kareyi aç → <Kbd>Enter</Kbd>
        </button>
        {packet?.image_id === r.image_id && <AnomalyChips imageId={r.image_id} vehicles={packet.vehicles} max={4} />}
        <details className="preview-more">
          <summary>Görüntü ve skor</summary>
          <p className="muted small">Risk skoru {r.score} / 100</p>
          <img className="preview-img" src={api.imageUrl(r.image_id)} alt={`${r.image_id} drone karesi (önizleme)`} loading="lazy" />
        </details>
      </div>
    </aside>
  );
}

/** The selected frame's evidence packet (vehicles for the chat chips), fetched once per frame. */
const packetCache = new Map<string, EvidencePacket>();
function usePacket(imageId: string | null) {
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  useEffect(() => {
    if (!imageId) return;
    const hit = packetCache.get(imageId);
    if (hit) return setPacket(hit);
    let alive = true;
    api
      .packet(imageId)
      .then((p) => {
        packetCache.set(imageId, p);
        if (alive) setPacket(p);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [imageId]);
  return packet;
}

type OverviewLayer = "rings" | "zones" | "minor" | "decided";
const OVERVIEW_LAYERS: { key: OverviewLayer; label: string }[] = [
  { key: "rings", label: "Mesafe halkaları" },
  { key: "zones", label: "Bölge adları" },
  { key: "minor", label: "DÜŞÜK / ORTA kareler" },
  { key: "decided", label: "Karar verilmiş kareler" },
];

function OverviewMap({
  ctx,
  hover,
  selected,
  visible,
  decided,
  alerts,
  onSelect,
}: {
  ctx: MapContext;
  hover: string | null;
  selected: string | null;
  visible: Set<string> | null;
  decided: Set<string>;
  alerts: Set<string>;
  onSelect: (imageId: string) => void;
}) {
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const mapRef = useRef<MLMap | null>(null);
  const markers = useRef<Record<string, Marker>>({});
  const zoneMarkers = useRef<Marker[]>([]);
  const [ready, setReady] = useState(0); // markers exist only after the map loads
  const { layers, toggle } = useLayers<OverviewLayer>("layers_overview", { rings: true, zones: true, minor: true, decided: true });
  const onReady = (map: MLMap) => {
    mapRef.current = map;
    Object.values(markers.current).forEach((m) => m.remove());
    zoneMarkers.current.forEach((m) => m.remove());
    markers.current = {};
    setGeo(map, "rings", fc(ctx.rings.map((r) => line(r.ring, { km: r.km }))));
    if (!map.getLayer("rings"))
      map.addLayer({
        id: "rings",
        type: "line",
        source: "rings",
        paint: { "line-color": token("--line-strong"), "line-width": 1, "line-dasharray": [3, 3] },
      });
    htmlMarker(map, ctx.base.center, baseSymbol(ctx.base.name), "mk mk-base");
    zoneMarkers.current = ctx.zones.map((z) => htmlMarker(map, z.center, z.label, "mk mk-zone"));
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
  // Visual hierarchy: active alerts are full size (KRİTİK filled), other frames are small, decided ones recede.
  useEffect(() => {
    for (const f of ctx.frames) {
      const el = markers.current[f.image_id]?.getElement();
      if (!el) continue;
      const done = decided.has(f.image_id);
      el.classList.toggle("mk-quiet", done);
      el.classList.toggle("mk-attn", !done && f.level === "KRİTİK");
      el.classList.toggle("mk-minor", !alerts.has(f.image_id));
    }
  }, [decided, alerts, ctx, ready]);
  // Layers + replay: a frame is shown if it has arrived and its layer is on; the selected frame always shows.
  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("rings")) map.setLayoutProperty("rings", "visibility", layers.rings ? "visible" : "none");
    zoneMarkers.current.forEach((m) => (m.getElement().style.display = layers.zones ? "" : "none"));
    for (const f of ctx.frames) {
      const el = markers.current[f.image_id]?.getElement();
      if (!el) continue;
      const arrived = !visible || visible.has(f.image_id);
      const hiddenByLayer =
        (!layers.decided && decided.has(f.image_id)) || (!layers.minor && (f.level === "DÜŞÜK" || f.level === "ORTA"));
      el.style.display = arrived && (!hiddenByLayer || f.image_id === selected) ? "" : "none";
    }
  }, [visible, layers, decided, selected, ctx, ready]);
  return (
    <MapView
      className="overview-map"
      onReady={onReady}
      initial={{ center: ctx.base.center, zoom: 11.6 }}
      controls={<LayerMenu defs={OVERVIEW_LAYERS} layers={layers} onToggle={toggle} />}
    />
  );
}

/** Legend from the symbol vocabulary (lib/symbols.ts): levels with their action, then report verdicts. */
function Legend() {
  return (
    <div className="legend">
      {LEVEL_LEGEND.map((l) => (
        <span key={l.level} className={`level ${LEVEL_CLASS[l.level]} level-sm`}>
          {l.icon} {l.level}: {l.action}
        </span>
      ))}
      {VERDICT_LEGEND.map((v) => (
        <span key={v.icon} className="legend-verdict">
          <b aria-hidden>{v.icon}</b> {v.text}
        </span>
      ))}
    </div>
  );
}
