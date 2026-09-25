import { LABEL_TR, LEVEL_COLOR, dec, scoreLevel } from "../lib/format";
import type { EvidencePacket } from "../lib/types";

const NEUTRAL = "#38bdf8";

/** Drone frame with detection boxes. Boxes are in image_meta pixel space, so the SVG uses that viewBox. */
export function ImagePanel({
  packet,
  url,
  focusTrack,
  onFocusTrack,
  blind = false,
}: {
  packet: EvidencePacket;
  url: string;
  focusTrack: string | null;
  onFocusTrack: (trackId: string | null) => void;
  /** Blind labelling: one neutral colour, so box colours do not reveal the system's scores. */
  blind?: boolean;
}) {
  const colorOf = (score: number) => (blind ? NEUTRAL : LEVEL_COLOR[scoreLevel(score)]);
  const { width_px: W, height_px: H } = packet.frame;
  return (
    <figure className="image-panel">
      <div className="image-box" style={{ aspectRatio: `${W} / ${H}` }}>
        <img src={url} alt={`${packet.image_id} drone karesi`} />
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
          {packet.vehicles.map((v) => {
            const [x, y, w, h] = v.bbox;
            const color = colorOf(v.score);
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
                  stroke={focused ? "#fff" : color}
                  strokeWidth={focused ? 4 : 2.5}
                  strokeDasharray={v.track_id ? undefined : "6 4"}
                  vectorEffect="non-scaling-stroke"
                />
                <text x={x} y={Math.max(12, y - 4)} className="box-label" fill={focused ? "#fff" : color}>
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
              className={v.track_id && v.track_id === focusTrack ? "active" : ""}
              onMouseEnter={() => onFocusTrack(v.track_id)}
            >
              <span className="swatch" style={{ background: colorOf(v.score) }} />
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
