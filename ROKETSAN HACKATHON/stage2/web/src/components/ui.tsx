import type { ReactNode } from "react";
import { LEVEL_CLASS, LEVEL_ICON, VERDICT_CLASS, VERDICT_ICON, splitRefs } from "../lib/format";
import type { Health, Level, VerdictT } from "../lib/types";

/** Level is always icon + text + colour (never colour alone). */
export function LevelBadge({ level, size = "md" }: { level: Level; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={`level ${LEVEL_CLASS[level]} level-${size}`}>
      <span className="level-icon" aria-hidden>
        {LEVEL_ICON[level]}
      </span>
      {level}
    </span>
  );
}

export function VerdictBadge({ verdict, compact }: { verdict: VerdictT; compact?: boolean }) {
  return (
    <span className={`verdict ${VERDICT_CLASS[verdict]}`} title={verdict}>
      <span aria-hidden>{VERDICT_ICON[verdict]}</span>
      {!compact && <span>{verdict}</span>}
    </span>
  );
}

/** Evidence chip: clicking it focuses the vehicle/track/report on the map and time slider. */
export function Chip({ id, onClick, active }: { id: string; onClick?: (id: string) => void; active?: boolean }) {
  return (
    <button className={`chip ${active ? "chip-active" : ""}`} onClick={() => onClick?.(id)} title="Kanıtı göster">
      {id}
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

export function TopBar({ health, left }: { health: Health | null; left?: ReactNode }) {
  const llmOk = health && !health.llm.error;
  const detFallback = health?.detector_fallback;
  return (
    <header className="topbar">
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
      <div className="topbar-right">
        {health && health.warmup.done < health.warmup.total && (
          <span className="pill pill-dim">
            Hazırlanıyor {health.warmup.done}/{health.warmup.total}
          </span>
        )}
        <span className={`pill ${detFallback ? "pill-warn" : ""}`} title={detFallback ?? "Aktif tespit modeli"}>
          Model: {health ? prettyDetector(health.detector) : "…"}
          {detFallback ? " (önbellek)" : ""}
        </span>
        <span className={`pill ${llmOk ? "pill-ok" : "pill-warn"}`} title={health?.llm.error ?? ""}>
          <span className={`dot ${llmOk ? "dot-ok" : "dot-warn"}`} aria-hidden />
          LLM {llmOk ? `çevrimiçi · ${health?.llm.model}` : "çevrimdışı · şablon brief"}
        </span>
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

export function ErrorState({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Bir sorun oluştu.</strong> {error}
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          Tekrar dene
        </button>
      )}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}
