import type { MapLayerMouseEvent, Map as MLMap, Marker } from "maplibre-gl";
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { go } from "../App";
import { MapView, fc, htmlMarker, line, polygon, setGeo } from "../components/MapView";
import { grid } from "../lib/geo";
import { LEVEL_LEGEND, VERDICT_LEGEND, baseSymbol, classSymbol } from "../lib/symbols";
import { ReplayBar, useReplay } from "../components/Replay";
import { TimeBar } from "../components/TimeBar";
import { AnomalyChips } from "../components/VehicleChip";
import { useVehicleLayer } from "../components/VehicleLayer";
import { DecisionPill, ErrorState, Kbd, LevelBadge, Loading, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { createClock, type Clock } from "../lib/clock";
import { threatAt, toMin } from "../lib/dayVehicles";
import { LABEL_TR, reducedMotion, LEVEL_ACTION, LEVEL_CLASS, LEVEL_ICON, dec, hhmm, km, secs, storage, zoneName } from "../lib/format";
import { LEVEL_VAR, levelColor, token } from "../lib/theme";
import type { DayVehicle, EvidencePacket, FrameMotion, Health, Label, LngLat, MapContext, ShiftSummary, TriageRow, VehicleDay } from "../lib/types";
import { addToChat, endDrag, frameItem, startDrag } from "../lib/vehicles";

/** Main map view: moving vehicles over the day (with the time bar) or one marker per frame. */
type MapMode = "vehicles" | "frames";

type MapFrame = MapContext["frames"][number];
const LABEL_ORDER: Label[] = ["truck", "bus", "van", "car", "unknown"]; // heavy first, as the risk model weighs them

/** Arrow length on the overview map: 34 px at rest up to 70 px at ≥ 80 km/h (visual encoding only). */
const ARROW_MIN_PX = 34;
const ARROW_MAX_PX = 70;
const ARROW_FULL_KMH = 80;
const CARD_FADE_OUT_MS = 250; // matches the .card-out animation in styles.css

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
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [error, setError] = useState<unknown>(null);
  // undefined: follow the most urgent frame · null: card closed · string: the operator's pick.
  const [pick, setPick] = useState<string | null | undefined>(undefined);
  const [hover, setHover] = useState<string | null>(null);
  const [hoverVeh, setHoverVeh] = useState<string | null>(null); // vehicle view: the vehicle under the pointer
  const [showTip, setShowTip] = useState(() => !storage.get("tip_seen", false));
  const viewed = useMemo(() => new Set(storage.get<string[]>("viewed", [])), []);
  const replay = useReplay();
  // Frames first: the alert rail, the map card and the decision flow are built on frames; vehicles are one click away.
  const [mode, setMode] = useState<MapMode>(() => storage.get<MapMode>("map_mode", "frames"));
  const [vehDay, setVehDay] = useState<VehicleDay | null>(null);
  const [threshold, setThreshold] = useState<number>(() => storage.get("veh_threshold", 0));
  const clock = useMemo(() => createClock({ t: -1, playing: false, speed: 2 }), []);
  const switchMode = (m: MapMode) => {
    storage.set("map_mode", m);
    setMode(m);
    clock.set({ playing: false });
  };
  const changeThreshold = (v: number) => {
    storage.set("veh_threshold", v);
    setThreshold(v);
  };
  useEffect(() => {
    if (mode === "vehicles" && !vehDay) api.vehicles().then(setVehDay).catch((e) => setError(e));
  }, [mode, vehDay]);

  const load = () => {
    setError(null);
    api
      .map()
      .then(setMapCtx)
      .catch((e) => setError(e));
  };
  useEffect(load, [queue]);

  // Risk-ordered (backend order): what the map shows and J/K walks through (during a replay, only arrived frames).
  const rows = useMemo(
    () => (queue ?? []).filter((r) => !replay.arrived || replay.arrived.has(r.image_id)),
    [queue, replay.arrived],
  );

  const selected = pick === null ? null : (rows.find((r) => r.image_id === pick) ?? rows[0] ?? null);
  const cursor = selected ? rows.indexOf(selected) : -1;
  const select = (id: string | null) => setPick(id);
  useEffect(() => onSelect?.(selected?.image_id ?? null), [selected?.image_id, onSelect]);
  useEffect(() => () => onSelect?.(null), [onSelect]);
  // Active alerts (YÜKSEK/KRİTİK without a decision, risk order): the rail on the left.
  const alerts = useMemo(() => rows.filter(isAlert), [rows]);
  const [railOpen, setRailOpen] = useState<boolean>(() => storage.get("rail_open", true));
  const toggleRail = () => {
    storage.set("rail_open", !railOpen);
    setRailOpen(!railOpen);
  };

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
      else if (e.key === " " && mode === "vehicles" && vehDay && tag !== "INPUT" && tag !== "BUTTON")
        clock.set({ playing: !clock.get().playing });
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [rows, cursor, selected, replay, mode, vehDay, clock]);

  const decided = useMemo(() => new Set((queue ?? []).filter((r) => r.decision).map((r) => r.image_id)), [queue]);
  const byId = useMemo(() => new Map((queue ?? []).map((r) => [r.image_id, r])), [queue]);
  const frameInfo = useMemo(() => new Map((mapCtx?.frames ?? []).map((f) => [f.image_id, f])), [mapCtx]);
  const vehById = useMemo(() => new Map((vehDay?.vehicles ?? []).map((v) => [v.id, v])), [vehDay]);
  // Time bar ticks: every frame at its capture time. The clock opens on the most urgent frame's moment.
  const ticks = useMemo(
    () => (mapCtx?.frames ?? []).map((f) => ({ image_id: f.image_id, t: toMin(f.capture_time), time: f.capture_time })),
    [mapCtx],
  );
  useEffect(() => {
    if (clock.get().t >= 0 || !vehDay || !ticks.length || !queue?.length) return;
    const first = ticks.find((k) => k.image_id === queue[0].image_id);
    clock.set({ t: first?.t ?? vehDay.window.end });
  }, [clock, vehDay, ticks, queue]);

  // Hovering previews a frame; the card stays while the pointer is on it, then falls back to the pick.
  const hoverTimer = useRef<number | undefined>(undefined);
  const hoverIn = (id: string) => {
    window.clearTimeout(hoverTimer.current);
    setHover(id);
    setHoverVeh(null);
  };
  // A vehicle opens its own card (its score and a cut-out of its box); its frame's footprint lights up behind it.
  const hoverVehIn = (v: DayVehicle) => {
    window.clearTimeout(hoverTimer.current);
    setHover(v.image_id);
    setHoverVeh(v.id);
  };
  const hoverKeep = () => window.clearTimeout(hoverTimer.current);
  const hoverOut = () => {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => {
      setHover(null);
      setHoverVeh(null);
    }, 180);
  };
  const shown = (hover && rows.some((r) => r.image_id === hover) ? byId.get(hover) : null) ?? selected;

  // The card on screen trails its target by one fade: a changed target first fades the old card out, then the new
  // one fades in (CSS animations; instant under prefers-reduced-motion). A vehicle card's key is "veh:<id>".
  const target = hoverVeh && vehById.get(hoverVeh)?.image_id ? `veh:${hoverVeh}` : (shown?.image_id ?? null);
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
  const cardVeh = cardId?.startsWith("veh:") ? vehById.get(cardId.slice(4)) : undefined;
  const cardFrame = cardVeh ? cardVeh.image_id : cardId;
  const cardRow = cardFrame ? byId.get(cardFrame) : undefined;
  const cardInfo = cardFrame ? frameInfo.get(cardFrame) : undefined;

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
        {replay.state && <ReplayBar r={replay} />}
        <div className="seg hud-panel map-mode" role="group" aria-label="Harita görünümü">
          <button className={`btn btn-sm ${mode === "vehicles" ? "seg-on" : "btn-ghost"}`} aria-pressed={mode === "vehicles"} onClick={() => switchMode("vehicles")}>
            Araçlar
          </button>
          <button className={`btn btn-sm ${mode === "frames" ? "seg-on" : "btn-ghost"}`} aria-pressed={mode === "frames"} onClick={() => switchMode("frames")}>
            Kareler
          </button>
        </div>
        {showTip && (
          <div className="tip hud-panel" role="note">
            {mode === "vehicles" ? (
              <span>
                Her işaret bir araç: seçili saatteki konumu, rengi tehdit seviyesi. Alttaki çubukla zamanı oynat (<Kbd>Space</Kbd>),
                eşikle kalabalığı azalt. Araca tıkla: karesinin kartı açılır. <Kbd>J</Kbd>/<Kbd>K</Kbd> kareleri risk sırasıyla gezer.
              </span>
            ) : (
              <span>
                Her işaret bir kare: üzerine gel ya da tıkla, kartı açılır. <Kbd>J</Kbd>/<Kbd>K</Kbd> risk sırasıyla gezer,{" "}
                <Kbd>Enter</Kbd> açar. Ok yalnızca üsse yaklaşan karelerde: öncü aracın yönü, uzunluğu hızı.
              </span>
            )}
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
            onVehicleHover={hoverVehIn}
            insets={insets}
            leftInset={railOpen && alerts.length ? RAIL_W + 16 : 0}
            card={
              cardVeh ? (
                <VehicleCard v={cardVeh} clock={clock} onHover={hoverKeep} onHoverOut={hoverOut} />
              ) : (
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
              ))
            }
            cardKey={cardId}
            cardLeaving={leaving}
            cardAt={cardInfo?.center ?? null}
            vehicles={mode === "vehicles" ? (vehDay?.vehicles ?? null) : null}
            threshold={threshold}
            clock={clock}
          />
        ) : (
          <Loading label="Kareler değerlendiriliyor" />
        )}
      </main>

      <AlertRail
        alerts={alerts}
        open={railOpen}
        onToggle={toggleRail}
        selected={selected?.image_id ?? null}
        viewed={viewed}
        isNew={replay.arrived ? replay.isNew : null}
        onSelect={select}
        insets={insets}
      />

      <div className="hud hud-bottom" ref={hudBottom}>
        {mode === "vehicles" && vehDay && (
          <TimeBar
            clock={clock}
            window={vehDay.window}
            ticks={ticks}
            vehicles={vehDay.vehicles}
            threshold={threshold}
            onThreshold={changeThreshold}
            onTick={select}
          />
        )}
        <Legend rings={mapCtx?.rings.map((r) => r.km) ?? []} />
      </div>
    </div>
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
  const packet = usePacket(r.image_id);
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
      <div className="action" role="note" style={{ ["--act" as string]: `var(${LEVEL_VAR[r.level]})` }}>
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
      {packet?.image_id === r.image_id && <AnomalyChips imageId={r.image_id} vehicles={packet.vehicles} max={4} />}
      <img className="preview-img" src={api.imageUrl(r.image_id)} alt={`${r.image_id} drone karesi (önizleme)`} loading="lazy" />
      <div className="frame-card-actions">
        <button className="btn btn-primary preview-open frame-card-open" onClick={() => go(`/frame/${r.image_id}`)}>
          Kareyi aç → <Kbd>Enter</Kbd>
        </button>
        <button className="btn" onClick={() => addToChat(frameItem(r))} aria-label={`${r.image_id} karesini sohbete ekle`}>
          Sor
        </button>
      </div>
    </aside>
  );
}

const THREAT_DIMS = [
  ["capability", "Yetenek"],
  ["opportunity", "Fırsat"],
  ["intent", "Niyet"],
] as const;

/** The clock's minute, re-rendering only when it changes (the clock ticks every animation frame while playing). */
function useClockMinute(clock: Clock): number {
  const [t, setT] = useState(() => Math.floor(clock.get().t));
  useEffect(() => clock.subscribe(() => setT(Math.floor(clock.get().t))), [clock]);
  return t;
}

/** Vehicle view: one vehicle's own card: its level and score (not its frame's), what they rest on, and the vehicle
 *  cut out of its frame around its detection box. Everything from GET /api/vehicles. */
function VehicleCard({
  v,
  clock,
  onHover,
  onHoverOut,
}: {
  v: DayVehicle;
  clock: Clock;
  onHover: () => void;
  onHoverOut: () => void;
}) {
  const t = useClockMinute(clock);
  // The head shows the same moment as the marker's colour: the level at the clock time (backend timeline).
  const now = t >= 0 ? threatAt(v, t) : null;
  const head = now ?? (v.level && v.score !== null ? { level: v.level, score: v.score } : null);
  const th = v.threat;
  return (
    <aside className="frame-card veh-card" aria-label="Seçili araç" onMouseEnter={onHover} onMouseLeave={onHoverOut}>
      <div className="frame-card-head">
        {head && <LevelBadge level={head.level} />}
        <span
          className="mono muted small frame-card-score"
          title={now ? `Bu aracın kendi risk skoru, saat ${hhmm(t)} itibarıyla (haritadaki renk)` : "Bu aracın kendi risk skoru (çekim anında)"}
        >
          {now ? `${hhmm(t)} · ` : ""}skor {head?.score ?? "—"}
        </span>
      </div>
      <div className="preview-id">
        <span className="mono">
          {v.vehicle_ref} · {v.label ? LABEL_TR[v.label] : "?"}
        </span>
        <span className="muted">
          {v.track_id ?? "hareket kaydı yok"} · {v.image_id} · {v.capture_time} · güven {dec(v.conf ?? 0, 2)}
        </span>
      </div>
      {v.image_id && v.vehicle_ref && (
        <div className="veh-crop-wrap">
          <img
            className="preview-img veh-crop"
            src={api.cropUrl(v.image_id, v.vehicle_ref)}
            alt={`${v.vehicle_ref}, ${v.image_id} karesinden kesit`}
          />
          {v.crop_box && (
            <span
              className="veh-crop-box"
              aria-hidden
              style={{
                left: `${v.crop_box[0] * 100}%`,
                top: `${v.crop_box[1] * 100}%`,
                width: `${v.crop_box[2] * 100}%`,
                height: `${v.crop_box[3] * 100}%`,
                ["--c" as string]: v.level ? levelColor(v.level) : "var(--accent)",
              }}
            />
          )}
        </div>
      )}
      <p className="muted small veh-card-at">{v.capture_time} çekimindeki kanıt</p>
      <dl className="facts">
        <dt>Çekimde</dt>
        <dd>
          skor {v.score} · {v.level}
        </dd>
        <dt>Üsse</dt>
        <dd className="mono">{v.d_base_m === null ? "—" : km(v.d_base_m)}</dd>
        <dt>ETA</dt>
        <dd className="mono">{v.approaching && v.eta_min !== null ? `~${dec(v.eta_min)} dk` : "yaklaşmıyor"}</dd>
        {th &&
          THREAT_DIMS.map(([key, name]) => (
            <Fragment key={key}>
              <dt>{name}</dt>
              <dd>
                <span className="mono">{th[key].score}</span> · {th[key].band}
              </dd>
            </Fragment>
          ))}
        {th?.floor_level && (
          <>
            <dt>Taban</dt>
            <dd>
              {th.floor_level}: {th.floor_reasons.join("; ")}
            </dd>
          </>
        )}
      </dl>
      <button className="btn btn-primary preview-open frame-card-open" onClick={() => go(`/frame/${v.image_id}`)}>
        Kareyi aç →
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
  onVehicleHover,
  insets,
  leftInset,
  card,
  cardKey,
  cardLeaving,
  cardAt,
  vehicles,
  threshold,
  clock,
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
  onVehicleHover: (v: DayVehicle) => void;
  /** Screen area covered by the floating layers (px from the top / bottom of the map). */
  insets: { top: number; bottom: number };
  /** Screen width covered by the alert rail on the left (the card keeps clear of it). */
  leftInset: number;
  card: ReactNode;
  cardKey: string | null;
  cardLeaving: boolean;
  cardAt: LngLat | null;
  /** Vehicle view: every vehicle of the day moved by the clock (null: frame view). */
  vehicles: DayVehicle[] | null;
  threshold: number;
  clock: Clock;
}) {
  const cb = useRef({ onSelect, onHover, onHoverOut, onVehicleHover });
  cb.current = { onSelect, onHover, onHoverOut, onVehicleHover };
  const markers = useRef<Record<string, Marker>>({});
  const arrows = useRef<Record<string, Marker>>({}); // heading arrows, laid on the map plane
  const mapRef = useRef<MLMap | null>(null);
  const footprintHandlers = useRef<MLMap | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(0); // markers exist only after the map loads
  const [pos, setPos] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  // Vehicle view: hovering a vehicle opens its own card next to the vehicle (not at the frame).
  const [vehAnchor, setVehAnchor] = useState<{ id: string; at: LngLat } | null>(null);
  useVehicleLayer({
    map: ready ? mapRef.current : null,
    ready,
    vehicles,
    enabled: vehicles !== null,
    threshold,
    clock,
    onSelect: (id) => cb.current.onSelect(id),
    onHover: (v, at) => {
      setVehAnchor({ id: `veh:${v.id}`, at });
      cb.current.onVehicleHover(v);
    },
    onHoverOut: () => cb.current.onHoverOut(),
  });
  const anchorAt = vehicles && vehAnchor && vehAnchor.id === cardKey ? vehAnchor.at : cardAt;

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
        paint: { "line-color": token("--muted"), "line-opacity": map.getTerrain() ? 0.3 : 0.14, "line-width": 1 },
      });
    setGeo(map, "rings", fc(ctx.rings.map((r) => line(r.ring, { km: r.km }))));
    if (!map.getLayer("rings"))
      map.addLayer({
        id: "rings",
        type: "line",
        source: "rings",
        paint: { "line-color": token("--muted"), "line-width": 1.25, "line-dasharray": [3, 3], "line-opacity": 0.7 }, // readable on the terrain texture too
      });
    // Frame footprints: each frame's real ground coverage, coloured by level (filled in by the effect below)
    setGeo(map, "frame-footprints", fc([]));
    if (!map.getLayer("frame-footprints-fill")) {
      map.addLayer({
        id: "frame-footprints-fill",
        type: "fill",
        source: "frame-footprints",
        paint: { "fill-color": ["get", "color"], "fill-opacity": ["get", "opacity"] },
      });
      map.addLayer({
        id: "frame-footprints-line",
        type: "line",
        source: "frame-footprints",
        paint: { "line-color": ["get", "outlineColor"], "line-width": ["get", "lineWidth"], "line-opacity": ["get", "lineOpacity"] },
      });
    }
    // Layer handlers live on the map, not the layer: bind them once per map, not on every style reload.
    if (footprintHandlers.current !== map) {
      footprintHandlers.current = map;
      const imageId = (e: MapLayerMouseEvent) => e.features?.[0]?.properties?.image_id as string | undefined;
      map.on("click", "frame-footprints-fill", (e) => {
        const id = imageId(e);
        if (id) cb.current.onSelect(id);
      });
      map.on("dblclick", "frame-footprints-fill", (e) => {
        const id = imageId(e);
        if (id) go(`/frame/${id}`);
      });
      map.on("mouseenter", "frame-footprints-fill", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "frame-footprints-fill", () => (map.getCanvas().style.cursor = ""));
    }
    htmlMarker(map, ctx.base.center, baseSymbol(ctx.base.name), "mk mk-base");
    for (const z of ctx.zones) htmlMarker(map, z.center, z.label, "mk mk-zone");
    // Arrows first (painted on the ground, under the upright icons); same point as the frame, so they tilt and
    // rotate with the plane and always point along the true heading.
    // Only frames whose lead vehicle approaches the base get an arrow: the threat stands out, not every movement.
    for (const f of ctx.frames) {
      if (!f.motion?.approaching) continue;
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
      // frame markers can be dragged into the chat, like the alert cards
      el.draggable = true;
      el.addEventListener("dragstart", (e) => startDrag(e, frameItem(f)));
      el.addEventListener("dragend", endDrag);
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

  // Footprints follow the filtered rows, selection, hover and decisions.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("frame-footprints")) return;
    const visible = new Set(rows.map((r) => r.image_id));
    const hover = shown !== selected ? shown : null;
    const features = ctx.frames
      .filter((f) => visible.has(f.image_id))
      .map((f) => {
        const isSel = f.image_id === selected;
        const isHov = f.image_id === hover;
        const isDec = decided.has(f.image_id);
        // Vehicle view: footprints are neutral (the vehicles carry the threat colour, not the frames).
        const color = isDec ? token("--line-strong") : vehicles ? token("--muted") : levelColor(f.level);
        return polygon([...f.corners, f.corners[0]], {
          image_id: f.image_id,
          color,
          opacity: isSel ? 0.35 : isHov ? 0.25 : isDec ? 0.04 : !vehicles && f.level === "KRİTİK" ? 0.2 : 0.08,
          outlineColor: isSel ? token("--text") : isHov ? token("--text-2") : color,
          lineWidth: isSel ? 2.5 : isHov ? 2 : isDec ? 1 : 1.5,
          lineOpacity: isDec ? 0.4 : 0.9,
        });
      });
    setGeo(map, "frame-footprints", fc(features));
  }, [rows, selected, shown, decided, ready, ctx, vehicles]);

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

  // The card follows its marker (or the hovered vehicle) as the map pans and zooms.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !anchorAt) return setPos(null);
    const update = () => {
      const p = map.project(anchorAt);
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
  }, [anchorAt?.[0], anchorAt?.[1], ready]); // eslint-disable-line react-hooks/exhaustive-deps

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
    const minLeft = 8 + leftInset;
    const top = insets.top + 8;
    const room = Math.max(160, pos.h - insets.bottom - 8 - top); // between the floating layers
    const h = Math.min(cardH ?? 0, room);
    style = {
      width: w,
      maxHeight: room,
      left: Math.max(minLeft, Math.min(left, pos.w - w - 8)),
      top: Math.max(top, Math.min(pos.y - 80, top + room - h)),
      visibility: cardH === null ? "hidden" : undefined, // first layout only: measured before it is painted
    };
  }

  return (
    <div className={`overview-stage${vehicles ? " veh-mode" : ""}`}>
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
        Lejant
      </button>
      {open && (
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
          <span className="legend-arrow">
            <svg width="26" height="10" viewBox="0 0 26 10" aria-hidden="true">
              <line x1="1" y1="5" x2="19" y2="5" />
              <path d="M17 1 L25 5 L17 9 Z" />
            </svg>
            yalnızca üsse yaklaşan karelerde: öncü aracın yönü · uzunluk = hız (≥ {ARROW_FULL_KMH} km/sa en uzun)
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

/** An active alert: YÜKSEK/KRİTİK with no operator decision yet (the rail's cards). */
const isAlert = (r: TriageRow) => !r.decision && (r.level === "KRİTİK" || r.level === "YÜKSEK");
const RAIL_W = 320;

/** Alert rail: the frames waiting for the operator, riskiest first, floating on the left of the map. Level and ETA
 *  first (the two facts that decide "now or later"); a click shows the frame's card on the map. */
function AlertRail({
  alerts,
  open,
  onToggle,
  selected,
  viewed,
  isNew,
  onSelect,
  insets,
}: {
  alerts: TriageRow[];
  open: boolean;
  onToggle: () => void;
  selected: string | null;
  viewed: Set<string>;
  isNew: ((id: string) => boolean) | null;
  onSelect: (id: string) => void;
  insets: { top: number; bottom: number };
}) {
  if (!alerts.length) return null;
  return (
    <section
      className={`rail hud-panel ${open ? "" : "rail-closed"}`}
      aria-label="Aktif uyarılar"
      style={{ top: insets.top + 8, bottom: insets.bottom + 8, width: open ? RAIL_W : undefined }}
    >
      <button className="rail-head" aria-expanded={open} onClick={onToggle}>
        <b>Aktif uyarılar</b> <span className="muted small">{alerts.length} karar bekliyor</span>
        <span className="muted small rail-toggle">{open ? "gizle" : "göster"}</span>
      </button>
      {open && (
        <ol className="rail-list">
          {alerts.map((r) => (
            <li
              key={r.image_id}
              className={`rail-card ${r.level === "KRİTİK" ? "rail-card-crit" : ""} ${r.image_id === selected ? "rail-on" : ""}`}
              onClick={() => onSelect(r.image_id)}
              onDoubleClick={() => go(`/frame/${r.image_id}`)}
              draggable
              onDragStart={(e) => startDrag(e, frameItem(r))}
              onDragEnd={endDrag}
              title="Tıkla: haritada kartı · çift tıkla: kareyi aç · sohbete sürükleyerek karşılaştır"
            >
              <div className="card-top">
                <LevelBadge level={r.level} size="sm" />
                <span className={`mono card-eta ${r.min_eta_min === null ? "muted" : ""}`}>
                  {r.min_eta_min === null ? "yaklaşan yok" : `ETA ~${dec(r.min_eta_min)} dk`}
                </span>
                {!viewed.has(r.image_id) && <span className="unseen" title="Bakılmadı" />}
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
                  {isNew?.(r.image_id) && <span className="tag tag-new">YENİ</span>}
                </span>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    addToChat(frameItem(r));
                  }}
                  aria-label={`${r.image_id} karesini sohbete ekle`}
                >
                  Sor
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** A frame's evidence packet (vehicles for the chat chips on the card), fetched once per frame. */
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
