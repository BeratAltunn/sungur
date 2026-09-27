// Duty-officer views (persona P2): the shift handover and a printable escalation card.
// Both only lay out what the backend returns (queue rows, packet, brief, decision log); nothing is computed.
import { type ReactNode, useEffect, useState } from "react";
import { go } from "../App";
import { DecisionPill, ErrorState, LevelBadge, Loading, TopBar, VerdictBadge } from "../components/ui";
import { api } from "../lib/api";
import { DECISION_TR, LEVEL_ACTION, LEVEL_ICON, SOURCE_TR, dec, km, secs, zoneName } from "../lib/format";
import { DecisionMetrics } from "./Triage";
import type { FrameResponse, Health, Level, ShiftHandover, TriageRow } from "../lib/types";

const stamp = (iso: string) => `${iso.slice(0, 10)} ${iso.slice(11, 16)}`; // backend times carry local offset
const nowStamp = () => new Date().toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
const eta = (r: TriageRow) => (r.min_eta_min === null ? "yaklaşan yok" : `ETA ~${dec(r.min_eta_min)} dk`);

function PrintActions({ text, back }: { text: string; back: { label: string; href: string } }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="print-actions no-print">
      <a className="btn btn-ghost btn-sm" href={back.href}>
        {back.label}
      </a>
      <button className="btn btn-sm" onClick={() => window.print()}>
        Yazdır
      </button>
      <button
        className="btn btn-sm"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
          } catch {
            /* clipboard blocked: printing still works */
          }
        }}
      >
        {copied ? "✓ Kopyalandı" : "Metni kopyala"}
      </button>
    </div>
  );
}

function RowLine({ r, extra }: { r: TriageRow; extra?: string }) {
  return (
    <li className="ho-row" onClick={() => go(`/frame/${r.image_id}`)}>
      <LevelBadge level={r.level} size="sm" />
      <span className="mono">{r.capture_time}</span>
      <span className="mono">{r.image_id}</span>
      <span>{zoneName(r.zone)}</span>
      <span className="mono">{km(r.d_base_m)}</span>
      <span className="mono">{eta(r)}</span>
      <span>{r.decision && <DecisionPill decision={r.decision} />}</span>
      <span className="ho-headline">{extra ?? r.headline}</span>
    </li>
  );
}

function rowText(r: TriageRow) {
  const d = r.decision;
  const who = d ? ` [${DECISION_TR[d.action]}${d.level ? ` → ${d.level}` : ""} ${d.at.slice(11, 16)}${d.reason ? `: ${d.reason}` : ""}]` : "";
  return `- ${LEVEL_ICON[r.level]} ${r.level} · ${r.image_id} · ${zoneName(r.zone)} · ${r.capture_time} · ${km(r.d_base_m)} · ${eta(r)}${who}\n  ${r.headline}`;
}

export function HandoverPage({ health }: { health: Health | null }) {
  const [h, setH] = useState<ShiftHandover | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setError(null);
    api.handover().then(setH).catch((e) => setError(e));
  };
  useEffect(load, []);

  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!h) return <Loading label="Vardiya devri hazırlanıyor" />;
  const s = h.summary;
  const levels = Object.entries(s.by_level)
    .map(([l, n]) => `${LEVEL_ICON[l as Level]} ${l} ${n}`)
    .join(" · ");
  const text = [
    `NÖBETÇİ · Vardiya devri · ${stamp(h.generated_at)}`,
    `${s.frames} kare · ${s.reports} rapor · ${levels}`,
    `${s.decided} karar verildi · ${h.awaiting.length} YÜKSEK/KRİTİK karar bekliyor`,
    `Karar süresi (açılış→karar): ${s.decision_median_s === null ? "henüz ölçüm yok" : `${secs(s.decision_median_s)} medyan, ${s.decision_timed} karar`}${s.high_decided ? ` · seviye düşürme ${s.high_downgraded}/${s.high_decided}` : ""}`,
    "",
    `AMİRE İLETİLENLER (${h.escalated.length})`,
    ...h.escalated.map(rowText),
    "",
    `KARAR BEKLEYEN YÜKSEK/KRİTİK (${h.awaiting.length})`,
    ...h.awaiting.map(rowText),
    "",
    `SEVİYESİ DEĞİŞTİRİLENLER (${h.overridden.length})`,
    ...h.overridden.map(rowText),
    "",
    `ONAYLANANLAR (${h.approved.length}): ${h.approved.map((r) => r.image_id).join(", ") || "—"}`,
    "",
    `KANITLA ÇELİŞEN RESMÎ RAPORLAR (${h.contradicted_official.length}; ayrıca ${h.contradicted_third_party} üçüncü taraf)`,
    ...h.contradicted_official.map(
      (r) => `- ✗ ${r.time} ${r.report_id}${r.identity_claim ? " (kimlik iddiası)" : ""}: "${r.text}"\n  → ${r.reason} [${r.frames.join(", ")}]`,
    ),
  ].join("\n");

  return (
    <div className="app">
      <TopBar health={health} />
      <main tabIndex={-1} className="print-page">
        <header className="print-head">
          <div>
            <h1>Vardiya devri</h1>
            <p className="muted">
              {stamp(h.generated_at)} · kurala dayalı özet (LLM kullanılmaz; her satır kuyruk, kanıt paketi ve karar
              kaydından gelir)
            </p>
          </div>
          <PrintActions text={text} back={{ label: "← Kuyruk", href: "#/" }} />
        </header>
        <p className="ho-summary">
          <strong>{s.frames}</strong> kare · <strong>{s.reports}</strong> rapor · {levels} · <strong>{s.decided}</strong> karar
          verildi · <strong className={h.awaiting.length ? "attn-text" : ""}>{h.awaiting.length} YÜKSEK/KRİTİK karar bekliyor</strong>
        </p>
        <p className="ho-summary">
          <DecisionMetrics summary={s} />
        </p>

        <Section title="Amire iletilenler" n={h.escalated.length} empty="Bu vardiyada amire iletilen kare yok.">
          {h.escalated.map((r) => (
            <RowLine key={r.image_id} r={r} />
          ))}
        </Section>
        <Section title="Karar bekleyen YÜKSEK/KRİTİK" n={h.awaiting.length} empty="Karar bekleyen yüksek riskli kare yok.">
          {h.awaiting.map((r) => (
            <RowLine key={r.image_id} r={r} />
          ))}
        </Section>
        <Section title="Seviyesi değiştirilenler" n={h.overridden.length} empty="Operatör seviye değiştirmedi.">
          {h.overridden.map((r) => (
            <RowLine key={r.image_id} r={r} extra={r.decision?.reason ? `Gerekçe: ${r.decision.reason}` : undefined} />
          ))}
        </Section>
        <Section title="Onaylananlar" n={h.approved.length} empty="Henüz onaylanan kare yok.">
          {h.approved.map((r) => (
            <RowLine key={r.image_id} r={r} />
          ))}
        </Section>
        <Section
          title="Kanıtla çelişen resmî raporlar"
          n={h.contradicted_official.length}
          note={`ayrıca ${h.contradicted_third_party} üçüncü taraf raporu`}
          empty="Kanıtla çelişen resmî rapor yok."
        >
          {h.contradicted_official.map((r) => (
            <li key={r.report_id} className="ho-report">
              <VerdictBadge verdict="ÇELİŞİYOR" compact />
              <span className="mono">
                {r.time} {r.report_id}
              </span>
              {r.identity_claim && <span className="pill pill-strong">kimlik iddiası</span>}
              <span className="ho-headline">
                “{r.text}” <span className="muted">→ {r.reason}</span>
              </span>
              <span className="ho-frames">
                {r.frames.map((f) => (
                  <a key={f} className="chip" href={`#/frame/${f}`}>
                    {f}
                  </a>
                ))}
              </span>
            </li>
          ))}
        </Section>
      </main>
    </div>
  );
}

function Section({
  title,
  n,
  note,
  empty,
  children,
}: {
  title: string;
  n: number;
  note?: string;
  empty: string;
  children: ReactNode;
}) {
  return (
    <section className="ho-section">
      <h2>
        {title} <span className="muted">({n})</span> {note && <span className="muted small">· {note}</span>}
      </h2>
      {n === 0 ? <p className="muted">{empty}</p> : <ul className="ho-list">{children}</ul>}
    </section>
  );
}

/** One page for the duty officer: the brief, its evidence and the operator's decision, ready to print. */
export function EscalationCard({ id, health }: { id: string; health: Health | null }) {
  const [f, setF] = useState<FrameResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api
      .frame(id)
      .then(setF)
      .catch((e) => setError(e));
  }, [id]);
  if (error) return <ErrorState error={error} />;
  if (!f) return <Loading label="Kart hazırlanıyor" />;
  const { brief: b, packet: p, grounding: g } = f.result;
  const bad = p.reports.filter((r) => r.verdict === "ÇELİŞİYOR");
  const d = f.decision;
  const text = [
    `[${LEVEL_ICON[b.risk_level]} ${b.risk_level}] ${id} · ${zoneName(p.frame.zone)} · ${p.frame.capture_time} · üsten ${km(p.frame.d_base_m)} ${p.frame.direction}`,
    b.headline,
    `Önerilen eylem: ${b.recommended_action}`,
    ...b.key_findings.map((k) => `- ${k.statement}`),
    ...(bad.length ? ["Kanıtla çelişen raporlar:", ...bad.map((r) => `- ✗ ${r.time} ${r.report_id} (${SOURCE_TR[r.source]}): ${r.reason}`)] : []),
    ...(b.uncertainties.length ? [`Belirsizlikler: ${b.uncertainties.join("; ")}`] : []),
    `Kanıt kontrolü: ${g.passed ? `${g.checked}/${g.checked} sayı doğrulandı` : "başarısız"} · güven ${b.confidence} · run_id ${f.result.run_id}`,
    ...(d ? [`Operatör kararı: ${DECISION_TR[d.action]}${d.level ? ` → ${d.level}` : ""} · ${stamp(d.at)}${d.reason ? ` · ${d.reason}` : ""}`] : []),
  ].join("\n");

  return (
    <div className="app">
      <TopBar health={health} />
      <main tabIndex={-1} className="print-page card-page">
        <header className="print-head">
          <div>
            <h1>Eskalasyon kartı</h1>
            <p className="muted">
              NÖBETÇİ · {nowStamp()} · sistem önerisidir, kararı insan verir
            </p>
          </div>
          <PrintActions text={text} back={{ label: "← Kareye dön", href: `#/frame/${id}` }} />
        </header>
        <div className="card-level">
          <LevelBadge level={b.risk_level} size="lg" />
          <span className="mono">{id}</span>
          <span>
            {zoneName(p.frame.zone)} · {p.frame.capture_time} · üsten {km(p.frame.d_base_m)} {p.frame.direction}
          </span>
        </div>
        <h2 className="card-headline">{b.headline}</h2>
        <div className="action" role="note">
          <span className="action-label">Önerilen eylem · {LEVEL_ACTION[b.risk_level]}</span>
          {b.recommended_action}
        </div>
        <ul className="findings">
          {b.key_findings.map((k, i) => (
            <li key={i}>{k.statement}</li>
          ))}
        </ul>
        {bad.length > 0 && (
          <section className="ho-section">
            <h2>Kanıtla çelişen raporlar</h2>
            <ul className="ho-list">
              {bad.map((r) => (
                <li key={r.report_id} className="ho-report">
                  <VerdictBadge verdict={r.verdict} compact />
                  <span className="mono">
                    {r.time} {r.report_id}
                  </span>
                  <span className="pill pill-dim">{SOURCE_TR[r.source]}</span>
                  <span className="ho-headline">
                    “{r.text}” <span className="muted">→ {r.reason}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
        {b.uncertainties.length > 0 && (
          <p className="muted">
            <strong>Belirsizlikler:</strong> {b.uncertainties.join(" · ")}
          </p>
        )}
        <p className="card-meta">
          <span className={`pill ${g.passed ? "" : "pill-strong"}`}>
            {g.passed ? `✓ ${g.checked}/${g.checked} sayı kanıtla doğrulandı` : "✗ Kanıt kontrolü başarısız"}
          </span>
          <span className="pill pill-dim">Güven: {b.confidence}</span>
          <span className="pill pill-dim mono">run_id {f.result.run_id}</span>
          {d ? <DecisionPill decision={d} /> : <span className="pill pill-dim">Operatör kararı yok</span>}
          {d?.reason && <span className="muted">Gerekçe: {d.reason}</span>}
        </p>
      </main>
    </div>
  );
}
