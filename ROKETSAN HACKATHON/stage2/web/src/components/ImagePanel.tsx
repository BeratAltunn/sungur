import { LABEL_TR, dec } from "../lib/format";
import { levelColor, token } from "../lib/theme";
import { endDrag, startDrag, vehicleItem } from "../lib/vehicles";
import type { EvidencePacket, Level } from "../lib/types";

const SCALE_CANDIDATES = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100];

/** Drone frame with detection boxes. Boxes are in image_meta pixel space, so the SVG uses that viewBox. */
export function ImagePanel({
  packet,
  url,
  focusTrack,
  onFocusTrack,
  levels,
  blind = false,
}: {
  packet: EvidencePacket;
  url: string;
  focusTrack: string | null;
  onFocusTrack: (trackId: string | null) => void;
  /** Per-vehicle level from the backend (config thresholds); omitted in blind mode. */
  levels?: Record<string, Level>;
  /** Blind labelling: one neutral colour, so box colours do not reveal the system's scores. */
  blind?: boolean;
}) {
  const colorOf = (ref: string) => (blind || !levels?.[ref] ? token("--text-2") : levelColor(levels[ref]));
  const { width_px: W, height_px: H, width_m: Wm, height_m: Hm } = packet.frame;
  const mpp = W > 0 && Wm > 0 ? Wm / W : 0.16;

  // Pick a clean metric round distance ~18% of frame width for the scale bar
  const targetM = (Wm || 150) * 0.18;
  const scaleM = SCALE_CANDIDATES.reduce((prev, curr) =>
    Math.abs(curr - targetM) < Math.abs(prev - targetM) ? curr : prev,
    25
  );
  const barWidthPx = mpp > 0 ? Math.round(scaleM / mpp) : 150;
  const scaleX = 20;
  const scaleY = H - 22;

  return (
    <figure className="image-panel">
      <div className="image-box" style={{ aspectRatio: `${W} / ${H}` }}>
        <img src={url} alt={`${packet.image_id} drone karesi`} />
        <div className="image-badge-hud" aria-label="Kare yer boyutu ve çözünürlük">
          <span className="mono">{dec(Wm, 0)} × {dec(Hm, 0)} m</span>
          <span className="hud-sep">·</span>
          <span>GSD ~{dec(mpp, 2)} m/px</span>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
          {packet.vehicles.map((v) => {
            const [x, y, w, h] = v.bbox;
            const color = colorOf(v.ref);
            const focused = !!v.track_id && v.track_id === focusTrack;
            const dimWm = dec(w * mpp, 1);
            const dimHm = dec(h * mpp, 1);
            return (
              <g
                key={v.ref}
                className="box"
                onMouseEnter={() => onFocusTrack(v.track_id)}
                onClick={() => onFocusTrack(v.track_id)}
              >
                <title>{`${v.ref} · ${LABEL_TR[v.label]} · ~${dimWm}×${dimHm} m (${Math.round(w)}×${Math.round(h)} px)`}</title>
                <rect
                  x={x}
                  y={y}
                  width={w}
                  height={h}
                  fill="none"
                  stroke={focused ? token("--text") : color}
                  strokeWidth={focused ? 4 : 2.5}
                  strokeDasharray={v.track_id ? undefined : "6 4"}
                  vectorEffect="non-scaling-stroke"
                />
                <text x={x} y={Math.max(12, y - 4)} className="box-label" fill={focused ? token("--text") : color}>
                  {v.ref}
                </text>
              </g>
            );
          })}

          {/* Metric scale bracket locked to image pixels */}
          <g className="svg-scale-bar" pointerEvents="none">
            <rect
              x={scaleX - 6}
              y={scaleY - 18}
              width={barWidthPx + 12}
              height="26"
              rx="4"
              fill={token("--overlay")}
              stroke={token("--line-strong")}
              strokeWidth="1"
            />
            <path
              d={`M ${scaleX},-5 L ${scaleX},2 L ${scaleX + barWidthPx},2 L ${scaleX + barWidthPx},-5`}
              transform={`translate(0, ${scaleY})`}
              fill="none"
              stroke={token("--text")}
              strokeWidth="2.5"
            />
            <text
              x={scaleX + barWidthPx / 2}
              y={scaleY - 6}
              textAnchor="middle"
              fill={token("--text")}
              fontSize="12"
              fontFamily="var(--mono)"
              fontWeight="700"
            >
              {scaleM} m
            </text>
          </g>
        </svg>
      </div>
      <figcaption>
        <ul className="box-legend">
          {packet.vehicles.map((v) => {
            const maxDimM = Math.max(v.bbox[2], v.bbox[3]) * mpp;
            return (
              <li
                key={v.ref}
                className={`${v.track_id && v.track_id === focusTrack ? "active" : ""} ${blind ? "" : "draggable"}`}
                onMouseEnter={() => onFocusTrack(v.track_id)}
                // any vehicle can be dragged into the chat (not in blind labelling: no chat there)
                draggable={!blind}
                title={blind ? undefined : "Sohbete sürükleyin"}
                onDragStart={(e) => startDrag(e, vehicleItem(packet.image_id, v))}
                onDragEnd={endDrag}
              >
                <span className="swatch" style={{ background: colorOf(v.ref) }} />
                <b>{v.ref}</b> {LABEL_TR[v.label]} · {v.track_id ?? "hareket kaydı yok"} · boy ~{dec(maxDimM, 1)} m · güven {dec(v.conf, 2)}
                {v.promoted ? " · track ile terfi" : ""}
              </li>
            );
          })}
        </ul>
        {packet.undetected_tracks.length > 0 && (
          <p className="muted">
            Karede olup tespit edilemeyen: {packet.undetected_tracks.join(", ")} (haritada gri)
          </p>
        )}
      </figcaption>
    </figure>
  );
}
