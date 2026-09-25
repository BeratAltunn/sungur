import type { Map as MLMap, Marker } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { go } from "../App";
import { MapView, fc, htmlMarker, line, setGeo } from "../components/MapView";
import { ErrorState, Kbd, LevelBadge, Loading, TopBar } from "../components/ui";
import { api } from "../lib/api";
import { LEVELS, LEVEL_ACTION, LEVEL_CLASS, LEVEL_ICON, km, storage, zoneName } from "../lib/format";
import type { Health, Level, MapContext, ShiftSummary, TriageRow } from "../lib/types";

export function TriagePage({ health, queue }: { health: Health | null; queue: TriageRow[] | null }) {
  const [summary, setSummary] = useState<ShiftSummary | null>(null);
  const [mapCtx, setMapCtx] = useState<MapContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zone, setZone] = useState<string>("");
  const [level, setLevel] = useState<Level | "">("");
  const [unseenOnly, setUnseenOnly] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [showTip, setShowTip] = useState(() => !storage.get("tip_seen", false));
  const viewed = useMemo(() => new Set(storage.get<string[]>("viewed", [])), []);

  const load = () => {
    setError(null);
    Promise.all([api.summary(), api.map()])
      .then(([s, m]) => {
        setSummary(s);
        setMapCtx(m);
      })
      .catch((e) => setError(String(e.message ?? e)));
  };
  useEffect(load, [queue]);

  const rows = useMemo(
    () =>
      (queue ?? []).filter(
        (r) => (!zone || r.zone === zone) && (!level || r.level === level) && (!unseenOnly || !viewed.has(r.image_id)),
      ),
    [queue, zone, level, unseenOnly, viewed],
  );

  // J/K move, Enter opens: the queue is operated from the keyboard.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "SELECT") return;
      if (e.key === "j" || e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, rows.length - 1));
      else if (e.key === "k" || e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
      else if (e.key === "Enter" && rows[cursor]) go(`/frame/${rows[cursor].image_id}`);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [rows, cursor]);

  useEffect(() => {
    document.querySelector(`[data-row="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const zones = useMemo(() => [...new Set((queue ?? []).map((r) => r.zone))].sort(), [queue]);

  return (
    <div className="app">
      <TopBar health={health} />
      {error && <ErrorState error={error} onRetry={load} />}
      {summary && <ShiftCard summary={summary} />}
      {showTip && (
        <div className="tip" role="note">
          <strong>Nasıl kullanılır:</strong> 1. Kuyruk en riskli kareden başlar · 2. Kareyi açınca önce brief, altında
          kanıt gelir · 3. <em>Neden?</em> sekmesi puanın nereden geldiğini gösterir. Bir rapora tıklayınca harita o
          saate gider.
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

      <main className="triage">
        <section className="queue panel" aria-label="Risk kuyruğu">
          <div className="panel-head">
            <h2>Kuyruk</h2>
            <div className="filters">
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
              <label className="check">
                <input type="checkbox" checked={unseenOnly} onChange={(e) => setUnseenOnly(e.target.checked)} />
                Sadece bakılmamışlar
              </label>
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
                  onClick={() => go(`/frame/${r.image_id}`)}
                  onMouseEnter={() => setHover(r.image_id)}
                  onMouseLeave={() => setHover(null)}
                >
                  <LevelBadge level={r.level} size="sm" />
                  <div className="row-main">
                    <div className="row-top">
                      <span className="mono">{r.image_id}</span>
                      <span>{zoneName(r.zone)}</span>
                      <span className="mono">{r.capture_time}</span>
                      <span className="mono">{km(r.d_base_m)}</span>
                      {r.reports_contradicted > 0 && (
                        <span className="verdict vd-bad" title="Kanıtla çelişen rapor">
                          ✗{r.reports_contradicted}
                        </span>
                      )}
                      {!viewed.has(r.image_id) && <span className="unseen" title="Bakılmadı" />}
                    </div>
                    <div className="row-headline">{r.headline}</div>
                  </div>
                  <span className="score mono" title="Risk skoru">
                    {r.score}
                  </span>
                </li>
              ))}
            </ol>
          )}
          <div className="hint">
            <Kbd>J</Kbd>/<Kbd>K</Kbd> gez · <Kbd>Enter</Kbd> aç
          </div>
        </section>

        <section className="panel overview" aria-label="Bölge haritası">
          <div className="panel-head">
            <h2>Bölge haritası</h2>
            <span className="muted">Üs merkezde · halkalar {mapCtx?.rings.map((r) => `${r.km} km`).join(" / ")}</span>
          </div>
          {mapCtx ? <OverviewMap ctx={mapCtx} hover={hover} /> : <Loading />}
          <Legend />
        </section>
      </main>
    </div>
  );
}

function ShiftCard({ summary }: { summary: ShiftSummary }) {
  const u = summary.most_urgent;
  return (
    <section className="shift" aria-label="Nöbet devri">
      <div className="shift-stats">
        <span className="shift-title">Nöbet devri</span>
        <span>
          <strong>{summary.frames}</strong> kare · <strong>{summary.reports}</strong> rapor işlendi
        </span>
        <span className="shift-levels">
          {LEVELS.map((l) => (
            <span key={l} className={`level ${LEVEL_CLASS[l]} level-sm`}>
              {LEVEL_ICON[l]} {l} {summary.by_level[l] ?? 0}
            </span>
          ))}
        </span>
        <span className="muted">{summary.contradicted_reports} rapor kanıtla çelişiyor</span>
      </div>
      {u && (
        <div className="shift-urgent">
          <span className="muted">En acil</span>
          <LevelBadge level={u.level} size="sm" />
          <span className="mono">{u.image_id}</span>
          <span>
            {zoneName(u.zone)} · {u.capture_time}
          </span>
          <span className="shift-headline">“{u.headline}”</span>
          <span className="muted">{LEVEL_ACTION[u.level]}</span>
          <button className="btn btn-primary" onClick={() => go(`/frame/${u.image_id}`)}>
            Kareyi aç →
          </button>
        </div>
      )}
    </section>
  );
}

function OverviewMap({ ctx, hover }: { ctx: MapContext; hover: string | null }) {
  const markers = useRef<Record<string, Marker>>({});
  const onReady = (map: MLMap) => {
    Object.values(markers.current).forEach((m) => m.remove());
    markers.current = {};
    setGeo(map, "rings", fc(ctx.rings.map((r) => line(r.ring, { km: r.km }))));
    if (!map.getLayer("rings"))
      map.addLayer({
        id: "rings",
        type: "line",
        source: "rings",
        paint: { "line-color": "#3b4656", "line-width": 1, "line-dasharray": [3, 3] },
      });
    htmlMarker(map, ctx.base.center, `<span>◆</span><b>${ctx.base.name}</b>`, "mk mk-base");
    for (const z of ctx.zones) htmlMarker(map, z.center, z.label, "mk mk-zone");
    for (const f of ctx.frames) {
      markers.current[f.image_id] = htmlMarker(
        map,
        f.center,
        `<span class="mk-frame-icon">${LEVEL_ICON[f.level]}</span>`,
        `mk mk-frame ${LEVEL_CLASS[f.level]}`,
        () => go(`/frame/${f.image_id}`),
      );
      markers.current[f.image_id].getElement().title = `${f.image_id} · ${zoneName(f.zone)} · ${f.capture_time} · ${f.level}`;
    }
  };
  useEffect(() => {
    for (const [id, m] of Object.entries(markers.current)) m.getElement().classList.toggle("mk-hover", id === hover);
  }, [hover]);
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
