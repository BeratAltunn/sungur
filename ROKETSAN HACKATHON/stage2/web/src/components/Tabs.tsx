import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { LABEL_TR, SOURCE_TR, STEP_TR, VERDICT_CLASS, dec, km, zoneName } from "../lib/format";
import type { EvaluationResult, EvidencePacket, LiveRun, TraceStep, VerdictT } from "../lib/types";
import { RefText, VerdictBadge } from "./ui";
import { VehicleChip } from "./VehicleChip";
import { anomalies } from "../lib/vehicles";

export type TabId = "why" | "reports" | "vehicles" | "trace";

export function EvidenceTabs({
  packet,
  res,
  tab,
  setTab,
  focusReport,
  onPickReport,
  onRef,
  only,
  live,
}: {
  only?: TabId[];
  /** A live run in progress: the trace tab shows its steps as they finish. */
  live?: LiveRun | null;
  packet: EvidencePacket;
  res: EvaluationResult | null;
  tab: TabId;
  setTab: (t: TabId) => void;
  focusReport: string | null;
  onPickReport: (id: string) => void;
  onRef: (id: string) => void;
}) {
  const n = (v: VerdictT) => packet.reports.filter((r) => r.verdict === v).length;
  const all: [TabId, string][] = [
    ["why", "Neden?"],
    ["reports", `Raporlar ✓${n("DOĞRULANDI")} ✗${n("ÇELİŞİYOR")} ?${n("DOĞRULANAMAZ")} —${n("İLGİSİZ")}`],
    ["vehicles", `Araçlar (${packet.vehicles.length})`],
    ["trace", "Ajan izi"],
  ];
  const tabs = all.filter(([id]) => !only || only.includes(id));
  return (
    <section className="panel tabs">
      <div
        role="tablist"
        className="tablist"
        aria-label="Kanıt"
        onKeyDown={(e) => {
          // ←/→ move between tabs (WAI-ARIA tabs pattern); only the selected tab is in the Tab order.
          const i = tabs.findIndex(([id]) => id === tab);
          const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
          if (!d) return;
          e.preventDefault();
          const next = tabs[(i + d + tabs.length) % tabs.length][0];
          setTab(next);
          document.getElementById(`tab-${next}`)?.focus();
        }}
      >
        {tabs.map(([id, label]) => (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            aria-selected={tab === id}
            aria-controls="tabpanel"
            tabIndex={tab === id ? 0 : -1}
            className={tab === id ? "tab tab-on" : "tab"}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="tabpanel" id="tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "why" && <WhyTab packet={packet} onRef={onRef} />}
        {tab === "reports" && <ReportsTab packet={packet} focus={focusReport} onPick={onPickReport} onRef={onRef} />}
        {tab === "vehicles" && <VehiclesTab packet={packet} onRef={onRef} />}
        {tab === "trace" && (live ? <LiveTrace live={live} /> : <TraceTab res={res} />)}
      </div>
    </section>
  );
}

function WhyTab({ packet, onRef }: { packet: EvidencePacket; onRef: (id: string) => void }) {
  const r = packet.risk;
  const vehicles = [...packet.vehicles].sort((a, b) => b.score - a.score);
  const max = Math.max(30, ...packet.vehicles.flatMap((v) => v.factors.map((f) => Math.abs(f.points))));
  return (
    <div className="why">
      <p>
        Kare skoru <b className="mono">{r.score}</b> = en riskli aracın skoru + kare düzeyi faktörler. Skor seviyesi{" "}
        <b>{r.score_level}</b>
        {r.floor_level ? (
          <>
            , taban kuralı <b>{r.floor_level}</b> → nihai <b>{r.level}</b>.
          </>
        ) : (
          "."
        )}
      </p>
      {r.floor_reasons.length > 0 && (
        <div className="floor">
          <b>Taban kuralı (LLM bunun altına inemez):</b>
          <ul>
            {r.floor_reasons.map((x, i) => (
              <li key={i}>
                <RefText text={x} onRef={onRef} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {vehicles.map((v) => (
        <div key={v.ref} className="factor-group">
          <div className="factor-head">
            <RefText text={`${v.ref} ${v.track_id ?? ""}`} onRef={onRef} /> <span className="muted">{LABEL_TR[v.label]}</span>
            <span className="mono score">{v.score}</span>
          </div>
          {v.factors.map((f, i) => (
            <div key={i} className="factor">
              <span className="factor-label">{f.label}</span>
              <span className="bar">
                <span className={f.points >= 0 ? "bar-pos" : "bar-neg"} style={{ width: `${(Math.abs(f.points) / max) * 100}%` }} />
              </span>
              <span className="mono pts">{f.points > 0 ? `+${f.points}` : f.points}</span>
            </div>
          ))}
        </div>
      ))}
      {r.factors.length > 0 && (
        <div className="factor-group">
          <div className="factor-head">Kare düzeyi</div>
          {r.factors.map((f, i) => (
            <div key={i} className="factor">
              <span className="factor-label">{f.label}</span>
              <span className="bar">
                <span className="bar-pos" style={{ width: `${(Math.abs(f.points) / max) * 100}%` }} />
              </span>
              <span className="mono pts">+{f.points}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReportsTab({
  packet,
  focus,
  onPick,
  onRef,
}: {
  packet: EvidencePacket;
  focus: string | null;
  onPick: (id: string) => void;
  onRef: (id: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const rows = packet.reports.filter((r) => showAll || r.verdict !== "İLGİSİZ");
  if (!packet.reports.length) return <p className="muted">Son 2 saatte bu kare için rapor yok. Bu durum riski düşürmez.</p>;
  return (
    <div>
      <label className="check">
        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> İlgisiz (bağlam) raporları da göster
      </label>
      <p className="muted small">Her rapor kendi saatindeki duruma göre doğrulanır. Satıra tıklayınca harita ve zaman kaydırıcısı o saate gider.</p>
      <table className="reports">
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.report_id}
              className={`${focus === r.report_id ? "tr-focus" : ""} ${VERDICT_CLASS[r.verdict]}-row`}
              onClick={() => r.claim.lat !== null && onPick(r.report_id)}
            >
              <td>
                <VerdictBadge verdict={r.verdict} />
              </td>
              <td className="mono">
                {r.report_id}
                <br />
                {r.time}
              </td>
              <td>
                <span className={`pill pill-dim ${r.source === "official" ? "" : "pill-3p"}`}>{SOURCE_TR[r.source]}</span>
                {r.identity_claim && <span className="pill pill-strong">kimlik iddiası</span>}
              </td>
              <td>
                <div className="report-text">{r.text}</div>
                <div className="report-reason">
                  → <RefText text={r.reason} onRef={onRef} />
                </div>
                <div className="muted small">{r.relevance}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Spark({ series }: { series: [string, number][] }) {
  if (series.length < 2) return null;
  const vals = series.map((s) => s[1]);
  const [lo, hi] = [Math.min(...vals), Math.max(...vals)];
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * 100},${hi === lo ? 10 : 20 - ((v - lo) / (hi - lo)) * 20}`).join(" ");
  return (
    <svg className="spark" viewBox="0 0 100 20" preserveAspectRatio="none" aria-label="Üsse mesafe (2 saat)">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function VehiclesTab({ packet, onRef }: { packet: EvidencePacket; onRef: (id: string) => void }) {
  return (
    <>
    <div className="table-scroll">
    <table className="vehicles">
      <thead>
        <tr>
          <th>Araç</th>
          <th>Sınıf · güven</th>
          <th>Eşleme</th>
          <th>Üsse</th>
          <th>Yaklaşma</th>
          <th>ETA</th>
          <th>2 saatte yol</th>
          <th>Duraklama</th>
          <th>Mesafe (2 sa)</th>
        </tr>
      </thead>
      <tbody>
        {packet.vehicles.map((v) => {
          const k = v.kinematics;
          return (
            <tr key={v.ref}>
              <td>
                {anomalies(v).length ? <VehicleChip imageId={packet.image_id} v={v} /> : <RefText text={`${v.ref} ${v.track_id ?? ""}`} onRef={onRef} />}
              </td>
              <td>
                {LABEL_TR[v.label]} · {dec(v.conf, 2)}
                {v.promoted && <span className="pill pill-dim">terfi</span>}
              </td>
              <td className="mono">{v.match_m !== null ? `${dec(v.match_m)} m (marj ${dec(v.margin_m ?? 0, 0)})` : "—"}</td>
              <td className="mono">
                {km(v.d_base_m)} {v.direction}
              </td>
              <td className="mono">{k ? `${dec(k.closing_mps)} m/s` : "—"}</td>
              <td className="mono">{k?.eta_min != null ? `~${dec(k.eta_min)} dk` : "—"}</td>
              <td className="mono">{k ? km(k.path_m) : "—"}</td>
              <td>{k ? (k.stops.length ? `${k.stops.length} · ${k.stop_total_min} dk` : "yok") : "—"}</td>
              <td className={k?.approaching ? "approach" : ""}>{k && <Spark series={k.d_series} />}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
    <ul className="zones-passed muted small">
      {packet.vehicles
        .filter((v) => v.kinematics)
        .map((v) => (
          <li key={v.ref}>
            <b>{v.ref}</b> geçtiği bölgeler: {v.kinematics!.zones_passed.map(zoneName).join(" → ")}
          </li>
        ))}
    </ul>
    </>
  );
}

/** One readable line per step from its output summary (formatting only; falls back to raw JSON). */
function stepLine(s: TraceStep): string {
  const o = s.output_summary as Record<string, any> | null;
  if (!o || typeof o !== "object") return typeof o === "string" ? o : "";
  try {
    if (s.step === "1_tespit") {
      const cls = Object.entries(o["sınıflar"] ?? {})
        .map(([k, v]) => `${v} ${LABEL_TR[k as keyof typeof LABEL_TR] ?? k}`)
        .join(", ");
      return `${o.n} kutu, ${o["conf>=0.4"]} tanesi güvenli${cls ? ` (${cls})` : ""}`;
    }
    if (s.step === "2_koordinat") return `kare merkezi üsse ${km(o["üsse_m"])} ${o["yön"]} · ${zoneName(o["bölge"])} · ${o.tespitler?.length ?? 0} tespit haritada`;
    if (s.step === "3_eşleme_kinematik") {
      const pairs = Object.entries(o["eşleşen"] ?? {}) as [string, { track: string; m: number }][];
      return `${pairs.length} araç hareket kaydıyla eşleşti: ${pairs.map(([v, p]) => `${v}→${p.track} (${dec(p.m)} m)`).join(" · ")}`;
    }
    if (s.step === "4_raporlar") {
      const k = o.kararlar ?? {};
      const bad = (o["çelişen"] ?? []) as string[];
      return `${o.ilgili} rapor kendi saatine göre doğrulandı: ✓${k["DOĞRULANDI"] ?? 0} ✗${k["ÇELİŞİYOR"] ?? 0} ?${k["DOĞRULANAMAZ"] ?? 0}${bad.length ? ` · çelişen ${bad.join(", ")}` : ""}`;
    }
    if (s.step === "5_risk") return `skor ${o.skor} → ${o.skor_seviyesi}${o.taban ? ` · taban kuralı ${o.taban}` : ""} · nihai ${o.seviye}`;
    if (s.step.startsWith("6_") && o["manşet"]) return `${o.seviye}: “${o["manşet"]}”`;
  } catch {
    /* unexpected shape: raw below */
  }
  return JSON.stringify(o).slice(0, 160);
}

const LIVE_SLOTS: [string, string][] = [
  ["1_tespit", "1 · Tespit"],
  ["2_koordinat", "2 · Koordinat"],
  ["3_eşleme_kinematik", "3 · Eşleme ve kinematik"],
  ["4_raporlar", "4 · Rapor doğrulama"],
  ["5_risk", "5 · Risk"],
  ["6_", "6 · Brief (LLM analist)"],
];

/** Live run: the six steps fill in as the backend finishes them (real durations, nothing simulated). */
function LiveTrace({ live }: { live: LiveRun }) {
  const match = (key: string, step: string) => (key === "6_" ? step.startsWith("6_") : step === key);
  return (
    <ol className="trace trace-live" aria-live="polite">
      {LIVE_SLOTS.map(([key, label]) => {
        const d = live.done.filter((s) => match(key, s.step)).at(-1);
        const running = !d && !!live.current && match(key, live.current);
        return (
          <li key={key} className={d ? (d.error ? "trace-err" : "live-done") : running ? "live-run" : "live-wait"}>
            <div className="trace-head">
              <span className="live-icon" aria-hidden>
                {d ? (d.error ? "✗" : "✓") : running ? <span className="spinner" /> : "○"}
              </span>
              <b>{d ? STEP_TR[d.step] ?? label : label}</b>
              {d && <span className="mono muted">{dec(d.duration_ms, 0)} ms</span>}
              {d?.cache_hit && <span className="pill pill-dim">önbellek</span>}
            </div>
            {d && <div className="trace-line">{d.error ?? stepLine(d)}</div>}
          </li>
        );
      })}
    </ol>
  );
}

function TraceTab({ res }: { res: EvaluationResult | null }) {
  const [steps, setSteps] = useState<TraceStep[] | null>(null);
  useEffect(() => {
    if (!res) return;
    api.trace(res.run_id).then(setSteps).catch(() => setSteps([]));
  }, [res]);
  if (!res || !steps) return <p className="muted">İz yükleniyor…</p>;
  return (
    <ol className="trace">
      {steps.map((s, i) => (
        <li key={i} className={s.error ? "trace-err" : ""}>
          <div className="trace-head">
            <b>{STEP_TR[s.step] ?? s.step}</b>
            <span className="mono muted">{dec(s.duration_ms, 0)} ms</span>
            {s.cache_hit && <span className="pill pill-dim">önbellek</span>}
            {s.llm && (
              <span className="pill pill-dim">
                {s.llm.model} · {s.llm.tokens_in}→{s.llm.tokens_out} token
              </span>
            )}
            {s.grounding && <span className="pill pill-dim">{s.grounding.checked} sayı kontrol edildi</span>}
          </div>
          {stepLine(s) && <div className="trace-line">{stepLine(s)}</div>}
          <details>
            <summary className="muted small">Girdi / çıktı</summary>
            <pre>{JSON.stringify({ girdi: s.input_summary, çıktı: s.output_summary, hata: s.error ?? undefined }, null, 1)}</pre>
          </details>
        </li>
      ))}
      <li className="muted small">run_id {res.run_id}</li>
    </ol>
  );
}
