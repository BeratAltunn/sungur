import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../lib/api";
import { DECISION_ICON, DECISION_TR, LEVEL_CLASS, LEVEL_ICON, VERDICT_CLASS, VERDICT_ICON, dec, splitRefs } from "../lib/format";
import type { Decision, Health, Level, ShiftSummary, VerdictT } from "../lib/types";

/** Level is always icon + text + colour (never colour alone). Tone "auto" fills KRİTİK (the one level that
 *  demands immediate attention), "quiet" drops the colour once the operator has decided, "outline" never fills. */
export function LevelBadge({
  level,
  size = "md",
  tone = "auto",
}: {
  level: Level;
  size?: "sm" | "md" | "lg";
  tone?: "auto" | "quiet" | "outline";
}) {
  const solid = tone === "auto" && level === "KRİTİK";
  return (
    <span className={`level ${LEVEL_CLASS[level]} level-${size} ${solid ? "level-solid" : ""} ${tone === "quiet" ? "level-quiet" : ""}`}>
      <span className="level-icon" aria-hidden>
        {LEVEL_ICON[level]}
      </span>
      {level}
    </span>
  );
}

/** Operator decision in the queue: icon + text (the level the operator set, for overrides). */
export function DecisionPill({ decision }: { decision: Decision }) {
  const d = decision;
  return (
    <span className={`pill decision-pill dp-${d.action}`} title={[`${d.at.slice(11, 16)} · ${DECISION_TR[d.action]}`, d.reason].filter(Boolean).join("\n")}>
      <span aria-hidden>{DECISION_ICON[d.action]}</span> {d.action === "override" && d.level ? `operatör: ${LEVEL_ICON[d.level]} ${d.level}` : DECISION_TR[d.action]}
    </span>
  );
}

export function VerdictBadge({ verdict, compact }: { verdict: VerdictT; compact?: boolean }) {
  return (
    <span className={`verdict ${VERDICT_CLASS[verdict]}`} title={verdict}>
      <span aria-hidden>{VERDICT_ICON[verdict]}</span>
      <span className={compact ? "sr-only" : undefined}>{verdict}</span>
    </span>
  );
}

/** Display labels for evidence ids on the open frame (e.g. R075 → "12:35"); the id itself stays the key. */
export const RefLabels = createContext<Record<string, string>>({});

/** Evidence chip: clicking it focuses the vehicle/track/report on the map and time slider. */
export function Chip({ id, onClick, active }: { id: string; onClick?: (id: string) => void; active?: boolean }) {
  const extra = useContext(RefLabels)[id];
  return (
    <button className={`chip ${active ? "chip-active" : ""}`} onClick={() => onClick?.(id)} title="Kanıtı göster">
      {id}
      {extra && <span className="chip-extra"> · {extra}</span>}
    </button>
  );
}

/** Text with V/T/R ids turned into clickable chips. */
export function RefText({ text, onRef, active }: { text: string; onRef?: (id: string) => void; active?: string | null }) {
  return (
    <>
      {splitRefs(text).map((p, i) =>
        p.ref ? <Chip key={i} id={p.ref} onClick={onRef} active={active === p.ref} /> : <span key={i}>{p.t}</span>,
      )}
    </>
  );
}

/** True once `busy` has lasted longer than `ms` (MIL-STD-1472: > 1 s of processing gets a visible message). */
export function useSlow(busy: boolean, ms = 1000) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!busy) return setSlow(false);
    const h = window.setTimeout(() => setSlow(true), ms);
    return () => window.clearTimeout(h);
  }, [busy, ms]);
  return slow;
}

/** Shift summary shared by the status bar and the queue (App refreshes it with the queue). */
export const SummaryContext = createContext<ShiftSummary | null>(null);

type St = "normal" | "standby" | "caution" | "serious" | "critical" | "off";

/** Subsystem indicator: status symbol + label + value (never colour alone). */
function Subsystem({ label, value, st, title }: { label: string; value: string; st: St; title?: string }) {
  return (
    <span className="subsys" title={title}>
      <span className={`st st-${st}`} aria-hidden />
      <span className="subsys-label">{label}</span>
      <span className="subsys-value">{value}</span>
      <span className="sr-only">durum: {ST_TR[st]}</span>
    </span>
  );
}
const ST_TR: Record<St, string> = { normal: "normal", standby: "hazırlanıyor", caution: "dikkat", serious: "ciddi", critical: "kritik", off: "kapalı" };

/** Local time and Zulu, updated once a second (MIL-STD-1472: dynamic values ≤ 1 Hz). */
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const h = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(h);
  }, []);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    <span className="clock" aria-label="Saat">
      <span className="clock-local">
        {p(now.getHours())}:{p(now.getMinutes())}:{p(now.getSeconds())}
      </span>
      <span className="clock-zulu">
        {p(now.getUTCHours())}:{p(now.getUTCMinutes())}Z
      </span>
    </span>
  );
}

/** Facility threat posture: the highest level still waiting for the operator. Informative only. */
function Posture({ s }: { s: ShiftSummary | null }) {
  if (!s) return null;
  if (!s.posture_level)
    return (
      <span className="posture posture-clear" title="Karar bekleyen kare yok">
        <span className="posture-label">Tehdit durumu</span>
        <span className="st st-normal" aria-hidden /> Bekleyen karar yok
      </span>
    );
  return (
    <a className="posture" href="#/" title="En yüksek seviyede karar bekleyen kareler (sistem kendiliğinden hiçbir eylem yapmaz)">
      <span className="posture-label">Tehdit durumu</span>
      <LevelBadge level={s.posture_level} size="sm" />
      <span>
        {s.posture_pending} karar bekliyor
      </span>
    </a>
  );
}

/** Global status bar: classification banner, brand, clock + posture, subsystem health.
 *  `blind` (gold-set labelling) hides the posture: it would reveal the system's levels. */
export function TopBar({ health, left, blind = false }: { health: Health | null; left?: ReactNode; blind?: boolean }) {
  const summary = useContext(SummaryContext);
  const ref = useRef<HTMLElement>(null);
  // Sticky bars below read the real height (the banner and wrapping change it).
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const set = () => document.documentElement.style.setProperty("--topbar-h", `${el.offsetHeight}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const llmOk = !!health && !health.llm.error;
  const detFallback = health?.detector_fallback;
  const warming = !!health && health.warmup.done < health.warmup.total;
  const b = health?.budget;
  return (
    <header className="topbar" ref={ref}>
      <div className="classification" role="note">
        TASNİF DIŞI · DEMO VERİSİ
      </div>
      <div className="topbar-row">
        <button className="skip" onClick={() => document.querySelector<HTMLElement>("main")?.focus()}>
          İçeriğe geç
        </button>
        <div className="topbar-left">
          <a className="brand" href="#/">
            <span className="brand-mark" aria-hidden>
              ▲
            </span>
            NÖBETÇİ
          </a>
          <span className="muted">Merkez Üs</span>
          {left}
        </div>
        <div className="topbar-center">
          <Clock />
          {!blind && <Posture s={summary} />}
        </div>
        <div className="topbar-right">
          <Subsystem
            label="Tespit"
            value={health ? `${prettyDetector(health.detector)}${detFallback ? " (önbellek)" : ""}` : "…"}
            st={!health ? "off" : detFallback ? "serious" : "normal"}
            title={detFallback ?? "Aktif tespit modeli"}
          />
          <Subsystem
            label="LLM"
            value={!health ? "…" : llmOk ? health.llm.model : "çevrimdışı · şablon brief"}
            st={!health ? "off" : llmOk ? "normal" : "serious"}
            title={health?.llm.error ?? "Brief ve sohbet için dil modeli"}
          />
          <Subsystem
            label="Veri"
            value={!health ? "…" : warming ? `hazırlanıyor ${health.warmup.done}/${health.warmup.total}` : `${health.data.frames} kare · ${health.data.reports} rapor`}
            st={!health ? "off" : warming ? "standby" : "normal"}
          />
          {b && (b.spent_usd > 0 || b.ratio >= 0.8) && (
            <Subsystem
              label="Bütçe"
              value={b.ratio >= 1 ? "doldu · şablon brief" : `$${dec(b.spent_usd, 2)} / $${dec(b.stop_usd, 0)}`}
              st={b.ratio >= 1 ? "critical" : b.ratio >= 0.8 ? "caution" : "normal"}
              title="LLM harcaması / durdurma sınırı. Sınırda LLM çağrıları durur, brief'ler şablondan gelir."
            />
          )}
        </div>
      </div>
    </header>
  );
}

function prettyDetector(name: string) {
  if (name.startsWith("yolo:")) return `Yedek ${name.slice(5)}`;
  if (name.startsWith("kaggle:")) return "Kaggle modeli";
  if (name === "oracle") return "Oracle (test)";
  return name;
}

export function Loading({ label = "Yükleniyor" }: { label?: string }) {
  return (
    <div className="state">
      <span className="spinner" aria-hidden />
      {label}…
    </div>
  );
}

/** Operational error: what happened, what to do, the code last (MIL-STD-1472 style messages). */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="state state-error" role="alert">
      <span className="err-icon" aria-hidden>
        ✗
      </span>
      <div className="err-body">
        <strong>{e ? e.message : String((error as Error)?.message ?? error)}</strong>
        {e && <span>{e.recovery}</span>}
        {e?.code != null && <span className="muted small">kod {e.code}</span>}
      </div>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Tekrar dene
        </button>
      )}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}
