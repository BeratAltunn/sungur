// Impact view: would the decision come before the vehicles reach the base? (PROJECT_DESIGN §1.2, §1.4)
// Everything here is laid out from GET /api/impact (a simulation of operator time run in the backend);
// the only arithmetic is placing marks on the axis.
import { useEffect, useState } from "react";
import { go } from "../App";
import { ErrorState, LevelBadge, Loading, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { dec, hhmm, zoneName } from "../lib/format";
import type { HandlingTime, Health, ImpactReport, SimFrame } from "../lib/types";

// Series colours (--s-sys, --s-man in styles.css) are a categorical pair validated for the dark surface;
// level colours (orange/red) stay reserved for risk levels.

function Source({ h }: { h: HandlingTime }) {
  if (h.source === "varsayım") return <span className="pill pill-strong">varsayım</span>;
  return (
    <span className="pill">
      {h.source} · n={h.n}
    </span>
  );
}

function Tile({ title, sys, man, note }: { title: string; sys: string; man: string; note?: string }) {
  return (
    <div className="tile">
      <div className="tile-title">{title}</div>
      <div className="tile-values">
        <span>
          <span className="mk-sys" aria-hidden /> NÖBETÇİ <strong>{sys}</strong>
        </span>
        <span>
          <span className="mk-man" aria-hidden /> Elle <strong>{man}</strong>
        </span>
      </div>
      {note && <div className="muted small">{note}</div>}
    </div>
  );
}

export function ImpactPage({ health }: { health: Health | null }) {
  const [r, setR] = useState<ImpactReport | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setError(null);
    api
      .impact()
      .then(setR)
      .catch((e) => setError(e));
  };
  useEffect(load, []);
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!r) return <Loading label="Vardiya simüle ediliyor" />;

  const s = r.summary;
  const k = s.by_level["KRİTİK"];
  const y = s.by_level["YÜKSEK"];
  const rows = r.frames
    .filter((f) => f.arrival_min !== null && (f.level === "KRİTİK" || f.level === "YÜKSEK"))
    .sort((a, b) => (a.level === b.level ? a.capture_min - b.capture_min : a.level === "KRİTİK" ? -1 : 1));
  const span = Math.max(...rows.map((f) => Math.max(f.manual_done, f.arrival_min!) - f.capture_min));
  const max = Math.ceil((span + 1) / 5) * 5;
  const ticks = Array.from({ length: max / 5 + 1 }, (_, i) => i * 5);
  const pct = (f: SimFrame, t: number) => `${((t - f.capture_min) / max) * 100}%`;

  return (
    <div className="app">
      <TopBar health={health} />
      <main tabIndex={-1} className="print-page impact">
        <header className="print-head">
          <div>
            <h1>Karar, araç üsse varmadan önce mi?</h1>
            <p className="muted">
              Vardiya simülasyonu: tek operatör günün karelerini geldikleri saatte işler. Elle: geliş sırasıyla, kare başına{" "}
              {dec(r.manual.minutes)} dk. NÖBETÇİ ile: risk sırasıyla, kare başına {dec(r.system.minutes)} dk. Karşılaştırma,
              karedeki en yakın yaklaşan aracın çekim anındaki ETA'sına göre tahmini varışladır.
            </p>
          </div>
          <div className="print-actions no-print">
            <a className="btn btn-ghost btn-sm" href="#/">
              ← Kuyruk
            </a>
            <a className="btn btn-primary btn-sm" href="#/?replay=1" title="Kuyrukta vardiyayı zamanla oynat">
              Vardiyayı oynat
            </a>
          </div>
        </header>

        <div className="tiles">
          <Tile
            title="▲▲ KRİTİK: karar araç varmadan önce"
            sys={`${k.system_before}/${k.with_eta}`}
            man={`${k.manual_before}/${k.with_eta}`}
          />
          <Tile
            title="▲ YÜKSEK: karar araç varmadan önce"
            sys={`${y.system_before}/${y.with_eta}`}
            man={`${y.manual_before}/${y.with_eta}`}
          />
          <Tile
            title="Çekimden karara (YÜKSEK/KRİTİK, medyan)"
            sys={s.system_median_delay_min === null ? "—" : `${dec(s.system_median_delay_min)} dk`}
            man={s.manual_median_delay_min === null ? "—" : `${dec(s.manual_median_delay_min)} dk`}
          />
        </div>

        <p className="params">
          Kare başına süre · Elle <strong>{dec(r.manual.minutes)} dk</strong> <Source h={r.manual} /> · NÖBETÇİ{" "}
          <strong>{dec(r.system.minutes)} dk</strong> <Source h={r.system} />
          <span className="muted small">
            {" "}
            (Elle: kronometre testinde ≥ 3 ölçüm olunca o kullanılır. NÖBETÇİ: ≥ 3 açılış → karar ölçümü olunca o
            kullanılır.)
          </span>
        </p>

        <section className="ho-section">
          <h2>Kare başına: çekimden sonra kaç dakikada karar, araç kaçıncı dakikada üste?</h2>
          <div className="legend-row" aria-hidden>
            <span>
              <span className="mk-sys" /> NÖBETÇİ kararı
            </span>
            <span>
              <span className="mk-man" /> Elle karar
            </span>
            <span>
              <span className="mk-arr" /> araçların tahmini varışı
            </span>
          </div>
          <div className="tl" role="table" aria-label="Kare başına karar ve varış zamanları">
            <div className="tl-row tl-axis" role="row">
              <span role="columnheader">Kare</span>
              <span className="tl-track" role="columnheader" aria-label="Çekimden sonra dakika">
                {ticks.map((t) => (
                  <span key={t} className="tl-tick" style={{ left: `${(t / max) * 100}%` }}>
                    {t}
                  </span>
                ))}
              </span>
              <span role="columnheader">Sonuç</span>
            </div>
            {rows.map((f) => (
              <div
                key={f.image_id}
                className="tl-row"
                role="row"
                onClick={() => go(`/frame/${f.image_id}`)}
                title={`${f.image_id} · çekim ${f.capture_time} · varış ~${hhmm(f.arrival_min!)} · NÖBETÇİ kararı ${hhmm(f.system_done)} · elle karar ${hhmm(f.manual_done)}`}
              >
                <span className="tl-label" role="cell">
                  <LevelBadge level={f.level} size="sm" />
                  <span className="mono">{f.capture_time}</span>
                  <span className="mono">{f.image_id}</span>
                  <span className="muted small">{zoneName(f.zone)}</span>
                </span>
                <span className="tl-track" role="cell">
                  {ticks.map((t) => (
                    <span key={t} className="tl-grid" style={{ left: `${(t / max) * 100}%` }} />
                  ))}
                  <span className="tl-arr" style={{ left: pct(f, f.arrival_min!) }} />
                  <span className="tl-dot mk-man" style={{ left: pct(f, f.manual_done) }} />
                  <span className="tl-dot mk-sys" style={{ left: pct(f, f.system_done) }} />
                </span>
                <span className="tl-out" role="cell">
                  <span>
                    NÖBETÇİ {hhmm(f.system_done)} {f.system_before ? "✓ önce" : "✗ sonra"}
                  </span>
                  <span className="muted">
                    Elle {hhmm(f.manual_done)} {f.manual_before ? "✓ önce" : "✗ sonra"} · varış ~{hhmm(f.arrival_min!)}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="ho-section">
          <h2>Varsayımlar</h2>
          <ul className="assumptions">
            {r.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
            <li>Bu bir operatör zamanı modelidir; risk skoruna, brief'e ve kanıt kontrolüne girmez.</li>
          </ul>
        </section>
      </main>
    </div>
  );
}
