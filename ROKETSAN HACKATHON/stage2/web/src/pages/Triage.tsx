import type { Map as MLMap, Marker } from "maplibre-gl";
import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { go } from "../App";
import { MapView, fc, htmlMarker, line, setGeo } from "../components/MapView";
import { grid } from "../lib/geo";
import { baseSymbol, classSymbol } from "../lib/symbols";
import { ReplayBar, useReplay } from "../components/Replay";
import { DecisionPill, ErrorState, Kbd, LevelBadge, Loading, SummaryContext, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { LABEL_TR, LEVELS, reducedMotion, LEVEL_ACTION, LEVEL_CLASS, LEVEL_COLOR, LEVEL_ICON, dec, km, secs, storage, zoneName } from "../lib/format";
import type { FrameMotion, Health, Label, Level, LngLat, MapContext, ShiftSummary, TriageRow } from "../lib/types";

type MapFrame = MapContext["frames"][number];
const LABEL_ORDER: Label[] = ["truck", "bus", "van", "car", "unknown"]; // heavy first, as the risk model weighs them

/** Arrow length on the overview map: 34 px at rest up to 70 px at ≥ 80 km/h (visual encoding only). */
const ARROW_MIN_PX = 34;
const ARROW_MAX_PX = 70;
const ARROW_FULL_KMH = 80;
const CARD_FADE_OUT_MS = 250; // matches the .card-out animation in styles.css

export function TriagePage({ health, queue }: { health: Health | null; queue: TriageRow[] | null }) {
  const summary = useContext(SummaryContext);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [zone, setZone] = useState<string>("");
  const [level, setLevel] = useState<Level | "">("");
  const [status, setStatus] = useState<Status>("");
  const [search, setSearch] = useState("");
  // undefined: follow the most urgent frame · null: card closed · string: the operator's pick.
  const [pick, setPick] = useState<string | null | undefined>(undefined);
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

  // Risk-ordered (backend order), filtered: what the map shows and J/K walks through.
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
  useEffect(() => setPick(undefined), [zone, level, status, search]);

  const selected = pick === null ? null : (rows.find((r) => r.image_id === pick) ?? rows[0] ?? null);
  const cursor = selected ? rows.indexOf(selected) : -1;
  const select = (id: string | null) => setPick(id);

  // J/K move, Enter opens, Esc closes the card: the map is operated from the keyboard.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "SELECT" || (tag === "INPUT" && e.key !== "Enter" && e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
      if (e.key === "j" || e.key === "ArrowDown") select(rows[Math.min(cursor + 1, rows.length - 1)]?.image_id ?? null);
      else if (e.key === "k" || e.key === "ArrowUp") select(rows[Math.max(cursor - 1, 0)]?.image_id ?? null);
      else if (e.key === "Enter" && selected) go(`/frame/${selected.image_id}`);
      else if (e.key === "Escape" && tag !== "INPUT" && selected) select(null);
      else if (e.key === " " && replay.state && tag !== "INPUT") replay.set({ playing: !replay.state.playing });
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [rows, cursor, selected, replay]);

  const zones = useMemo(() => [...new Set((queue ?? []).map((r) => r.zone))].sort(), [queue]);
  const decided = useMemo(() => new Set((queue ?? []).filter((r) => r.decision).map((r) => r.image_id)), [queue]);
  const byId = useMemo(() => new Map((queue ?? []).map((r) => [r.image_id, r])), [queue]);
  const frameInfo = useMemo(() => new Map((mapCtx?.frames ?? []).map((f) => [f.image_id, f])), [mapCtx]);

  // Hovering previews a frame; the card stays while the pointer is on it, then falls back to the pick.
  const hoverTimer = useRef<number | undefined>(undefined);
  const hoverIn = (id: string) => {
    window.clearTimeout(hoverTimer.current);
    setHover(id);
  };
  const hoverOut = () => {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => setHover(null), 180);
  };
  const shown = (hover && rows.some((r) => r.image_id === hover) ? byId.get(hover) : null) ?? selected;

  // The card on screen trails `shown` by one fade: a changed target first fades the old card out, then the new
  // one fades in (CSS animations; instant under prefers-reduced-motion).
  const target = shown?.image_id ?? null;
  const [cardId, setCardId] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    if (target === cardId) return setLeaving(false);
    if (cardId === null) return setCardId(target);
    setLeaving(true);
    const t = window.setTimeout(
      () => {
        setCardId(target);
        setLeaving(false);
      },
      reducedMotion() ? 0 : CARD_FADE_OUT_MS,
    );
    return () => window.clearTimeout(t);
  }, [target, cardId]);
  const cardRow = cardId ? byId.get(cardId) : undefined;
  const cardInfo = cardId ? frameInfo.get(cardId) : undefined;

  // The map is the page background; everything else floats over it. The card and the map controls keep clear of
  // the floating layers, so their real extent is measured.
  const hudTop = useRef<HTMLDivElement>(null);
  const hudBottom = useRef<HTMLDivElement>(null);
  const [insets, setInsets] = useState({ top: 0, bottom: 0 });
  useLayoutEffect(() => {
    const measure = () => {
      const top = Math.ceil(hudTop.current?.getBoundingClientRect().bottom ?? 0);
      const b = hudBottom.current?.getBoundingClientRect();
      const bottom = b ? Math.ceil(window.innerHeight - b.top) : 0;
      document.documentElement.style.setProperty("--hud-top", `${top}px`);
      setInsets((p) => (p.top === top && p.bottom === bottom ? p : { top, bottom }));
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (hudTop.current) ro.observe(hudTop.current);
    if (hudBottom.current) ro.observe(hudBottom.current);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return (
    <div className="app app-map">
      {/* Floating layers first in the DOM: Tab reaches the skip link and the tools before the map. */}
      <div className="hud hud-top" ref={hudTop}>
        <TopBar health={health} />
        {error != null && <ErrorState error={error} onRetry={load} />}
        {replay.state ? (
          <ReplayBar r={replay} />
        ) : (
          summary && <ShiftStrip summary={summary} onReplay={replay.start} />
        )}
        <div className="hud-tools hud-panel" role="search">
          <span className="hud-count mono" title="Haritada gösterilen kare sayısı">
            {rows.length}
            {replay.arrived ? " geldi" : " kare"}
          </span>
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
        {showTip && (
          <div className="tip hud-panel" role="note">
            <span>
              Her işaret bir kare: üzerine gel ya da tıkla, kartı açılır. <Kbd>J</Kbd>/<Kbd>K</Kbd> risk sırasıyla gezer,{" "}
              <Kbd>Enter</Kbd> açar. Ok öncü aracın yönü, uzunluğu hızı.
            </span>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                storage.set("tip_seen", true);
                setShowTip(false);
              }}
            >
              Anladım
            </button>
          </div>
        )}
      </div>

      {/* Common operational picture: the map is the background; each frame opens a card next to its marker. */}
      <main tabIndex={-1} className="map-bg" aria-label="Bölge haritası">
        {mapCtx && queue ? (
          <OverviewMap
            ctx={mapCtx}
            rows={rows}
            selected={selected?.image_id ?? null}
            shown={shown?.image_id ?? null}
            decided={decided}
            viewed={viewed}
            isNew={replay.arrived ? replay.isNew : null}
            onSelect={select}
            onHover={hoverIn}
            onHoverOut={hoverOut}
            insets={insets}
            card={
              cardRow &&
              cardInfo && (
                <FrameCard
                  row={cardRow}
                  info={cardInfo}
                  isNew={!!replay.arrived && replay.isNew(cardRow.image_id)}
                  pinned={cardRow.image_id === selected?.image_id}
                  onClose={() => {
                    setHover(null);
                    select(null);
                  }}
                  onPin={() => select(cardRow.image_id)}
                  onHover={() => hoverIn(cardRow.image_id)}
                  onHoverOut={hoverOut}
                />
              )
            }
            cardKey={cardId}
            cardLeaving={leaving}
            cardAt={cardInfo?.center ?? null}
          />
        ) : (
          <Loading label="Kareler değerlendiriliyor" />
        )}
        {queue && rows.length === 0 && <div className="map-empty hud-panel">Bu filtreyle eşleşen kare yok.</div>}
      </main>

      <div className="hud hud-bottom" ref={hudBottom}>
        <Legend rings={mapCtx?.rings.map((r) => r.km) ?? []} />
      </div>
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
  const [open, setOpen] = useState(false);
  return (
    <section className="shift hud-panel" aria-label="Nöbet devri">
      <div className="shift-stats">
        <span className="shift-levels">
          {LEVELS.map((l) => (
            <span key={l} className={`level ${LEVEL_CLASS[l]} level-sm`} title={`${l}: ${summary.by_level[l] ?? 0} kare`}>
              {LEVEL_ICON[l]} {summary.by_level[l] ?? 0}
            </span>
          ))}
        </span>
        <strong className={summary.awaiting_high ? "warn-text" : ""}>{summary.awaiting_high} YÜKSEK/KRİTİK karar bekliyor</strong>
        <span className="shift-links">
          <button className="btn btn-ghost btn-sm" onClick={onReplay} title="Günü simüle saatle oynat: kareler çekim saatinde kuyruğa düşer">
            ▶ Oynat
          </button>
          <a className="btn btn-ghost btn-sm" href="#/handover" title="Amir için kurala dayalı vardiya özeti (yazdırılabilir)">
            Devir →
          </a>
          <a className="btn btn-ghost btn-sm" href="#/impact" title="Vardiya simülasyonu: karar, araçlar üsse varmadan önce mi?">
            Etki →
          </a>
          <button className="btn btn-ghost btn-sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            Ayrıntı {open ? "▴" : "▾"}
          </button>
        </span>
      </div>
      {open && (
        <div className="shift-more">
          <span>
            <strong>{summary.frames}</strong> kare · <strong>{summary.reports}</strong> rapor · {summary.contradicted_reports} rapor
            çelişiyor · {summary.decided} karar
          </span>
          <DecisionMetrics summary={summary} />
        </div>
      )}
    </section>
  );
}

/** Everything the alert row and the old preview panel showed, as a card next to the frame's marker (all from the
 *  backend: the queue row and the map context's lead-vehicle motion). */
function FrameCard({
  row: r,
  info,
  isNew,
  pinned,
  onClose,
  onPin,
  onHover,
  onHoverOut,
}: {
  row: TriageRow;
  info: MapFrame;
  isNew: boolean;
  pinned: boolean;
  onClose: () => void;
  onPin: () => void;
  onHover: () => void;
  onHoverOut: () => void;
}) {
  const m = info.motion;
  const classes = LABEL_ORDER.filter((lb) => info.label_counts[lb]);
  return (
    <aside
      className={`frame-card ${pinned ? "frame-card-pinned" : ""}`}
      aria-label="Seçili kare"
      onMouseEnter={onHover}
      onMouseLeave={onHoverOut}
      onClick={pinned ? undefined : onPin}
    >
      <div className="frame-card-head">
        <LevelBadge level={r.level} tone={r.decision ? "quiet" : "auto"} />
        {r.decision && <DecisionPill decision={r.decision} />}
        {isNew && <span className="tag tag-new">YENİ</span>}
        <span className="mono muted small frame-card-score" title="Risk skoru">
          skor {r.score}
        </span>
        <button className="btn btn-ghost btn-sm frame-card-close" onClick={onClose} aria-label="Kartı kapat" title="Kartı kapat (Esc)">
          ✕
        </button>
      </div>
      <div className="preview-id">
        <span className="mono">{r.image_id}</span>
        <span className="muted">
          {zoneName(r.zone)} · {r.capture_time} · üsten {km(r.d_base_m)}
        </span>
      </div>
      <p className="preview-headline">{r.headline}</p>
      <div className="action" role="note" style={{ ["--act" as string]: LEVEL_COLOR[r.level] }}>
        <span className="action-label">Seviye eylemi</span>
        {LEVEL_ACTION[r.level]}
      </div>
      <dl className="facts">
        <dt>En kısa ETA</dt>
        <dd className="mono">{r.min_eta_min === null ? "yaklaşan yok" : `~${dec(r.min_eta_min)} dk`}</dd>
        <dt>Hareket</dt>
        <dd>
          {m ? (
            <>
              <span className="mono">
                {m.heading_dir ?? "—"} {Math.round(m.heading_deg)}° · {dec(m.speed_kmh, 0)} km/sa
              </span>{" "}
              <span className="muted">
                ({m.track_id} {LABEL_TR[m.label]}, {m.approaching ? "üsse yaklaşıyor" : "üsse yaklaşmıyor"}
                {m.n_moving > 1 ? `; ${m.n_moving} hareketli araç` : ""})
              </span>
            </>
          ) : (
            <span className="muted">hareketli araç yok</span>
          )}
        </dd>
        <dt>Araç</dt>
        <dd>
          {r.n_vehicles} · {r.n_approaching} yaklaşan · {r.n_heavy} ağır
        </dd>
        <dt>Sınıflar</dt>
        <dd className="card-classes">
          {classes.length === 0 ? (
            <span className="muted">araç yok</span>
          ) : (
            classes.map((lb) => (
              <span key={lb} className="card-class">
                <span className="card-sil" dangerouslySetInnerHTML={{ __html: classSymbol(lb) }} />
                {info.label_counts[lb]} {LABEL_TR[lb]}
              </span>
            ))
          )}
        </dd>
        <dt>Raporlar</dt>
        <dd>
          <span className="verdict vd-ok">✓{r.reports_confirmed}</span>{" "}
          <span className="verdict vd-bad">✗{r.reports_contradicted}</span>
        </dd>
      </dl>
      <img className="preview-img" src={api.imageUrl(r.image_id)} alt={`${r.image_id} drone karesi (önizleme)`} loading="lazy" />
      <button className="btn btn-primary preview-open frame-card-open" onClick={() => go(`/frame/${r.image_id}`)}>
        Kareyi aç → <Kbd>Enter</Kbd>
      </button>
    </aside>
  );
}

function arrowHtml(m: FrameMotion) {
  const len = Math.round(ARROW_MIN_PX + (Math.min(m.speed_kmh, ARROW_FULL_KMH) / ARROW_FULL_KMH) * (ARROW_MAX_PX - ARROW_MIN_PX));
  return (
    `<span class="mk-arrow ${m.approaching ? "mk-arrow-in" : ""}" style="--hd:${m.heading_deg}deg;height:${len}px" aria-hidden="true">` +
    `<svg width="12" height="${len}" viewBox="0 0 12 ${len}"><line x1="6" y1="24" x2="6" y2="${len - 6}"/>` +
    `<path d="M1 ${len - 8} L6 ${len} L11 ${len - 8} Z"/></svg></span>`
  );
}

/** Main map opens tilted; right-drag / Ctrl+drag re-orients the plane, the compass resets it. */
const MAP_3D = { pitch: 45, maxPitch: 70 };
/** Faint 1 km reference grid around the base (vehicles reach ~8 km): shows the plane's tilt and heading. */
const GRID = { halfM: 10_000, stepM: 1_000 };
const CARD_W = 340;
const CARD_GAP = 28;

function OverviewMap({
  ctx,
  rows,
  selected,
  shown,
  decided,
  viewed,
  isNew,
  onSelect,
  onHover,
  onHoverOut,
  insets,
  card,
  cardKey,
  cardLeaving,
  cardAt,
}: {
  ctx: MapContext;
  rows: TriageRow[];
  selected: string | null;
  shown: string | null;
  decided: Set<string>;
  viewed: Set<string>;
  isNew: ((id: string) => boolean) | null;
  onSelect: (imageId: string) => void;
  onHover: (imageId: string) => void;
  onHoverOut: () => void;
  /** Screen area covered by the floating layers (px from the top / bottom of the map). */
  insets: { top: number; bottom: number };
  card: ReactNode;
  cardKey: string | null;
  cardLeaving: boolean;
  cardAt: LngLat | null;
}) {
  const cb = useRef({ onSelect, onHover, onHoverOut });
  cb.current = { onSelect, onHover, onHoverOut };
  const markers = useRef<Record<string, Marker>>({});
  const arrows = useRef<Record<string, Marker>>({}); // heading arrows, laid on the map plane
  const mapRef = useRef<MLMap | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(0); // markers exist only after the map loads
  const [pos, setPos] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  const onReady = (map: MLMap) => {
    mapRef.current = map;
    Object.values(markers.current).forEach((m) => m.remove());
    Object.values(arrows.current).forEach((m) => m.remove());
    markers.current = {};
    arrows.current = {};
    setGeo(map, "grid", fc(grid(ctx.base.center, GRID.halfM, GRID.stepM).map((l) => line(l))));
    if (!map.getLayer("grid"))
      map.addLayer({
        id: "grid",
        type: "line",
        source: "grid",
        // faint on the plain background; a little stronger over the satellite texture, where 0.14 vanishes
        paint: { "line-color": "#9fbcdb", "line-opacity": map.getTerrain() ? 0.3 : 0.14, "line-width": 1 },
      });
    setGeo(map, "rings", fc(ctx.rings.map((r) => line(r.ring, { km: r.km }))));
    if (!map.getLayer("rings"))
      map.addLayer({
        id: "rings",
        type: "line",
        source: "rings",
        paint: { "line-color": "#5b7ea3", "line-width": 1.25, "line-dasharray": [3, 3] }, // readable on the terrain texture too
      });
    htmlMarker(map, ctx.base.center, baseSymbol(ctx.base.name), "mk mk-base");
    for (const z of ctx.zones) htmlMarker(map, z.center, z.label, "mk mk-zone");
    // Arrows first (painted on the ground, under the upright icons); same point as the frame, so they tilt and
    // rotate with the plane and always point along the true heading.
    for (const f of ctx.frames) {
      if (!f.motion) continue;
      const a = htmlMarker(map, f.center, arrowHtml(f.motion), `mk-arrow-mk ${LEVEL_CLASS[f.level]}`, undefined, true);
      a.getElement().dataset.arrow = f.image_id;
      arrows.current[f.image_id] = a;
    }
    for (const f of ctx.frames) {
      const mk = htmlMarker(
        map,
        f.center,
        (f.lead_label
          ? `${classSymbol(f.lead_label)}<span class="mk-lv">${LEVEL_ICON[f.level]}</span>`
          : `<span class="mk-frame-icon">${LEVEL_ICON[f.level]}</span>`),
        `mk mk-frame ${LEVEL_CLASS[f.level]}`,
        () => cb.current.onSelect(f.image_id), // pin the card; double-click opens
      );
      const el = mk.getElement();
      el.dataset.frame = f.image_id;
      el.setAttribute("role", "button");
      el.tabIndex = -1;
      el.addEventListener("dblclick", () => go(`/frame/${f.image_id}`));
      el.addEventListener("mouseenter", () => cb.current.onHover(f.image_id));
      el.addEventListener("mouseleave", () => cb.current.onHoverOut());
      el.addEventListener("focus", () => cb.current.onSelect(f.image_id));
      markers.current[f.image_id] = mk;
    }
    setReady((r) => r + 1);
  };

  // Visibility (filters, replay) and the accessible name follow the filtered, risk-ordered rows.
  useEffect(() => {
    const byId = new Map(rows.map((r) => [r.image_id, r]));
    for (const f of ctx.frames) {
      const el = markers.current[f.image_id]?.getElement();
      if (!el) continue;
      const r = byId.get(f.image_id);
      el.classList.toggle("mk-hidden", !r);
      el.classList.toggle("mk-new", !!r && !!isNew?.(f.image_id));
      el.classList.toggle("mk-seen", viewed.has(f.image_id));
      const done = decided.has(f.image_id);
      el.classList.toggle("mk-quiet", done); // visual quiet: undecided KRİTİK frames are filled; decided ones recede
      el.classList.toggle("mk-attn", !done && f.level === "KRİTİK");
      const arrow = arrows.current[f.image_id]?.getElement();
      arrow?.classList.toggle("mk-hidden", !r);
      arrow?.classList.toggle("mk-quiet", done);
      if (r) {
        const mo = f.motion;
        el.setAttribute(
          "aria-label",
          `${r.level}, ${r.image_id}, ${zoneName(r.zone)}, ${r.capture_time}, üsse ${km(r.d_base_m)}, ${r.min_eta_min === null ? "yaklaşan yok" : `ETA yaklaşık ${dec(r.min_eta_min)} dakika`}${f.lead_label ? `, ${LABEL_TR[f.lead_label]}` : ""}${mo ? `, öncü araç ${mo.heading_dir ?? ""} yönünde ${dec(mo.speed_kmh, 0)} km/sa` : ""}${r.reports_contradicted ? `, ${r.reports_contradicted} rapor çelişiyor` : ""}${r.decision ? ", karar verildi" : ""}. ${r.headline}`,
        );
        el.title = `${r.image_id} · ${zoneName(r.zone)} · ${r.capture_time} · ${r.level}${f.lead_label ? ` · ${LABEL_TR[f.lead_label]}` : ""}${mo ? ` · ${mo.heading_dir ?? ""} ${dec(mo.speed_kmh, 0)} km/sa` : ""}`;
      }
    }
  }, [rows, ctx, decided, viewed, isNew, ready]);

  // Roving focus: the map is one Tab stop; J/K move the selection and, if a marker has focus, the focus too.
  useEffect(() => {
    const first = selected ?? rows[0]?.image_id ?? null;
    for (const [id, m] of Object.entries(markers.current)) {
      const el = m.getElement();
      el.tabIndex = id === first ? 0 : -1;
      el.classList.toggle("mk-selected", id === selected);
      el.classList.toggle("mk-hover", id === shown && id !== selected);
    }
    const map = mapRef.current;
    const el = selected ? markers.current[selected]?.getElement() : null;
    if (!map || !el) return;
    if (document.activeElement?.classList.contains("mk-frame") && document.activeElement !== el) el.focus({ preventScroll: true });
    // Keep the selection on screen when the keyboard walks to a marker outside the view.
    const p = map.project(markers.current[selected!].getLngLat());
    const c = map.getContainer();
    if (p.x < 40 || p.y < insets.top + 40 || p.x > c.clientWidth - 40 || p.y > c.clientHeight - insets.bottom - 40)
      map.easeTo({ center: markers.current[selected!].getLngLat(), duration: 300 });
  }, [selected, shown, rows, ready]);

  // The card follows its marker as the map pans and zooms.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !cardAt) return setPos(null);
    const update = () => {
      const p = map.project(cardAt);
      const c = map.getContainer();
      setPos({ x: p.x, y: p.y, w: c.clientWidth, h: c.clientHeight });
    };
    update();
    map.on("move", update);
    map.on("resize", update);
    return () => {
      map.off("move", update);
      map.off("resize", update);
    };
  }, [cardAt, ready]);

  // The card's real height, measured after layout (before paint) and again whenever its content resizes
  // (e.g. the thumbnail loads), so it is placed from its actual size, never last render's.
  const [cardH, setCardH] = useState<number | null>(null);
  useLayoutEffect(() => {
    const h = cardRef.current?.offsetHeight ?? null;
    if (h !== cardH) setCardH(h);
  });
  const hasCard = !!card && !!pos;
  useEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setCardH(el.offsetHeight));
    ro.observe(el.firstElementChild ?? el);
    return () => ro.disconnect();
  }, [hasCard, cardKey]);

  let style: CSSProperties | undefined;
  if (pos) {
    const w = Math.min(CARD_W, pos.w - 16);
    const right = pos.x + CARD_GAP;
    const left = right + w > pos.w - 8 ? pos.x - CARD_GAP - w : right;
    const top = insets.top + 8;
    const room = Math.max(160, pos.h - insets.bottom - 8 - top); // between the floating layers
    const h = Math.min(cardH ?? 0, room);
    style = {
      width: w,
      maxHeight: room,
      left: Math.max(8, Math.min(left, pos.w - w - 8)),
      top: Math.max(top, Math.min(pos.y - 80, top + room - h)),
      visibility: cardH === null ? "hidden" : undefined, // first layout only: measured before it is painted
    };
  }

  return (
    <div className="overview-stage">
      <MapView className="overview-map" onReady={onReady} initial={{ center: ctx.base.center, zoom: 11.6 }} threeD={MAP_3D} terrain />
      {card && style && (
        <div key={cardKey} ref={cardRef} className={`frame-card-wrap ${cardLeaving ? "card-out" : "card-in"}`} style={style}>
          {card}
        </div>
      )}
    </div>
  );
}

function Legend({ rings }: { rings: number[] }) {
  const [open, setOpen] = useState<boolean>(() => storage.get("legend_open", false));
  const toggle = () => {
    storage.set("legend_open", !open);
    setOpen(!open);
  };
  return (
    <div className="legend-box hud-panel">
      <button className="btn btn-ghost btn-sm legend-toggle" aria-expanded={open} onClick={toggle}>
        Lejant {open ? "▾" : "▸"}
      </button>
      {open && (
        <div className="legend">
          {LEVELS.map((l) => (
            <span key={l} className={`level ${LEVEL_CLASS[l]} level-sm`}>
              {LEVEL_ICON[l]} {l}: {LEVEL_ACTION[l]}
            </span>
          ))}
          <span className="legend-arrow">
            <svg width="26" height="10" viewBox="0 0 26 10" aria-hidden="true">
              <line x1="1" y1="5" x2="19" y2="5" />
              <path d="M17 1 L25 5 L17 9 Z" />
            </svg>
            öncü aracın yönü · uzunluk = hız (≥ {ARROW_FULL_KMH} km/sa en uzun) · renkli ok: üsse yaklaşıyor
          </span>
          <span className="muted">Halkalar: üsten {rings.map((k) => `${k} km`).join(" / ")}</span>
          <span className="muted">
            Sol tık + sürükle: kaydır · sağ tık (ya da <Kbd>Ctrl</Kbd>) + sürükle: döndür ve eğ · pusula: kuzey ve düz görünüm
          </span>
          <span className="muted">
            <Kbd>J</Kbd>/<Kbd>K</Kbd> gez · <Kbd>Enter</Kbd> aç · <Kbd>Esc</Kbd> kartı kapat · çift tıklama aç
          </span>
        </div>
      )}
    </div>
  );
}
