import { LABEL_TR, dec } from "../lib/format";
import { levelColor, token } from "../lib/theme";
import { DRAG_TYPE, toFocus } from "../lib/vehicles";
import type { EvidencePacket, Level } from "../lib/types";

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
  const { width_px: W, height_px: H } = packet.frame;
  return (
    <figure className="image-panel">
      <div className="image-box" style={{ aspectRatio: `${W} / ${H}` }}>
        <img src={url} alt={`${packet.image_id} drone karesi`} />
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
          {packet.vehicles.map((v) => {
            const [x, y, w, h] = v.bbox;
            const color = colorOf(v.ref);
            const focused = !!v.track_id && v.track_id === focusTrack;
            return (
              <g
                key={v.ref}
                className="box"
                onMouseEnter={() => onFocusTrack(v.track_id)}
                onClick={() => onFocusTrack(v.track_id)}
              >
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
        </svg>
      </div>
      <figcaption>
        <ul className="box-legend">
          {packet.vehicles.map((v) => (
            <li
              key={v.ref}
              className={`${v.track_id && v.track_id === focusTrack ? "active" : ""} ${blind ? "" : "draggable"}`}
              onMouseEnter={() => onFocusTrack(v.track_id)}
              // any vehicle can be dragged into the chat (not in blind labelling: no chat there)
              draggable={!blind}
              title={blind ? undefined : "Sohbete sürükleyin"}
              onDragStart={(e) => {
                e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(toFocus(packet.image_id, v)));
                e.dataTransfer.effectAllowed = "copy";
                document.body.classList.add("dragging-vehicle");
              }}
              onDragEnd={() => document.body.classList.remove("dragging-vehicle")}
            >
              <span className="swatch" style={{ background: colorOf(v.ref) }} />
              <b>{v.ref}</b> {LABEL_TR[v.label]} · {v.track_id ?? "hareket kaydı yok"} · güven {dec(v.conf, 2)}
              {v.promoted ? " · track ile terfi" : ""}
            </li>
          ))}
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
