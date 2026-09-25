import { useState } from "react";
import { api } from "../lib/api";
import { LEVELS, LEVEL_ICON, zoneName } from "../lib/format";
import type { Decision, EvaluationResult, Level } from "../lib/types";
import { Kbd, LevelBadge, RefText } from "./ui";

const SOURCE_TR = { llm: "LLM", llm_cache: "LLM (önbellek)", template: "Kural tabanlı şablon" } as const;

export function BriefPanel({
  res,
  onRef,
  activeRef,
}: {
  res: EvaluationResult | null;
  onRef: (id: string) => void;
  activeRef: string | null;
}) {
  if (!res) return <BriefSkeleton />;
  const { brief: b, packet: p, grounding: g } = res;
  const diff = b.risk_level !== p.risk.level;
  return (
    <section className="panel brief" aria-label="Brief">
      <div className="brief-head">
        <LevelBadge level={b.risk_level} size="lg" />
        <span className="muted mono">skor {p.risk.score}</span>
        {p.risk.floor_level && (
          <span className="pill pill-dim" title={p.risk.floor_reasons.join("\n")}>
            Taban kuralı: {p.risk.floor_level}
          </span>
        )}
      </div>
      {diff && (
        <p className="note">
          Kural seviyesi {p.risk.level}; LLM {b.risk_level} önerdi: {b.level_rationale}
        </p>
      )}
      <h1 className="headline">
        <RefText text={b.headline} onRef={onRef} active={activeRef} />
      </h1>
      <div className="action" role="note">
        <span className="action-label">Önerilen eylem</span>
        {b.recommended_action}
      </div>
      <ul className="findings">
        {b.key_findings.map((f, i) => (
          <li key={i}>
            <RefText text={f.statement} onRef={onRef} active={activeRef} />
          </li>
        ))}
      </ul>
      <div className="brief-meta">
        <span className={`pill ${g.passed ? "pill-ok" : "pill-warn"}`} title={[...g.failed, ...g.unknown_refs].join("\n")}>
          {g.passed ? `✓ ${g.checked}/${g.checked} sayı kanıtla doğrulandı` : "✗ Kanıt kontrolü başarısız"}
        </span>
        <span className="pill pill-dim">Güven: {b.confidence}</span>
        <span className={`pill ${res.brief_source === "template" ? "pill-warn" : "pill-dim"}`} title={res.llm_note ?? ""}>
          Kaynak: {SOURCE_TR[res.brief_source]}
        </span>
      </div>
      {res.llm_note && <p className="muted small">{res.llm_note}</p>}
      {b.uncertainties.length > 0 && (
        <details className="uncertain" open>
          <summary>Belirsizlikler ({b.uncertainties.length})</summary>
          <ul>
            {b.uncertainties.map((u, i) => (
              <li key={i}>
                <RefText text={u} onRef={onRef} active={activeRef} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function BriefSkeleton() {
  return (
    <section className="panel brief" aria-busy>
      <div className="skeleton sk-badge" />
      <div className="skeleton sk-line" />
      <div className="skeleton sk-line short" />
      <p className="muted">Brief hazırlanıyor (LLM). Kanıtlar aşağıda hazır.</p>
    </section>
  );
}

export function FrameHeader({ id, zone, capture, dist, dir }: { id: string; zone: string; capture: string; dist: string; dir: string }) {
  return (
    <div className="frame-title">
      <a className="btn btn-ghost btn-sm" href="#/" title="Kuyruğa dön (Esc)">
        ← Kuyruk
      </a>
      <h2 className="mono">{id}</h2>
      <span>
        {zoneName(zone)} · {capture} · üsten {dist} {dir}
      </span>
    </div>
  );
}

/** Operator decision: the system only recommends; every decision is appended to decisions.jsonl. */
export function DecisionBar({
  res,
  decision,
  onDecision,
}: {
  res: EvaluationResult | null;
  decision: Decision | null;
  onDecision: (d: Decision | null, toast: string) => void;
}) {
  const [overriding, setOverriding] = useState(false);
  const [level, setLevel] = useState<Level>("YÜKSEK");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!res) return null;
  const id = res.packet.image_id;

  const send = async (action: Decision["action"], extra: { level?: Level; reason?: string } = {}, toast = "") => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.decide(id, { run_id: res.run_id, action, ...extra });
      onDecision(r.decision, toast);
      setOverriding(false);
      setReason("");
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const escalate = async () => {
    const b = res.brief;
    const text = [
      `[${b.risk_level}] ${id} · ${zoneName(res.packet.frame.zone)} · ${res.packet.frame.capture_time}`,
      b.headline,
      ...b.key_findings.map((f) => `- ${f.statement}`),
      `Önerilen eylem: ${b.recommended_action}`,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard may be blocked; the decision is still recorded */
    }
    await send("escalate", {}, "Amire iletildi · brief panoya kopyalandı");
  };

  return (
    <div className="decision">
      {decision && (
        <span className="pill pill-dim" title={decision.reason}>
          Karar: {DECISION_TR[decision.action]}
          {decision.level ? ` → ${decision.level}` : ""} · {decision.at.slice(11, 16)}
        </span>
      )}
      <button data-hot="approve" className="btn btn-ok" disabled={busy} onClick={() => send("approve", {}, "Değerlendirme onaylandı")}>
        Onayla <Kbd>A</Kbd>
      </button>
      <button className="btn" disabled={busy} onClick={() => setOverriding((o) => !o)}>
        Seviyeyi değiştir
      </button>
      <button data-hot="escalate" className="btn btn-danger" disabled={busy} onClick={escalate}>
        Amire ilet <Kbd>E</Kbd>
      </button>
      {decision && (
        <button className="btn btn-ghost" disabled={busy} onClick={() => send("undo", {}, "Son karar geri alındı")}>
          Geri al
        </button>
      )}
      {overriding && (
        <form
          className="override"
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim()) send("override", { level, reason }, `Seviye ${level} olarak değiştirildi`);
          }}
        >
          <select value={level} onChange={(e) => setLevel(e.target.value as Level)} aria-label="Yeni seviye">
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {LEVEL_ICON[l]} {l}
              </option>
            ))}
          </select>
          <input
            autoFocus
            placeholder="Gerekçe (zorunlu)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-label="Gerekçe"
          />
          <button className="btn btn-primary" disabled={!reason.trim() || busy}>
            Kaydet
          </button>
        </form>
      )}
      {err && <span className="err">{err}</span>}
    </div>
  );
}

const DECISION_TR = { approve: "onaylandı", override: "seviye değişti", escalate: "amire iletildi", undo: "geri alındı" };
