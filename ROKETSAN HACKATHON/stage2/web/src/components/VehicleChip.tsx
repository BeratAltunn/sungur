import { LABEL_TR } from "../lib/format";
import type { Vehicle } from "../lib/types";
import { DRAG_TYPE, anomalies, anomalous, focusChat, toFocus } from "../lib/vehicles";

/** A vehicle the operator can drag into the chat (or send with "Sor"). Shows why it is unusual. */
export function VehicleChip({ imageId, v }: { imageId: string; v: Vehicle }) {
  const f = toFocus(imageId, v);
  const why = anomalies(v).slice(0, 2);
  return (
    <span
      className="vchip"
      draggable
      title="Sohbete sürükleyin: sorular bu araca göre değişir"
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(f));
        e.dataTransfer.setData("text/plain", `${v.ref} ${v.track_id ?? ""}`.trim());
        e.dataTransfer.effectAllowed = "copy";
        document.body.classList.add("dragging-vehicle");
      }}
      onDragEnd={() => document.body.classList.remove("dragging-vehicle")}
    >
      <span className="vchip-id">
        <b>{v.ref}</b> {LABEL_TR[v.label]}
        {v.track_id && <span className="mono"> · {v.track_id}</span>}
      </span>
      {why.length > 0 && <span className="vchip-why">{why.join(" · ")}</span>}
      <button className="vchip-ask" onClick={() => focusChat(f)} aria-label={`${v.ref} aracını sohbete ekle`}>
        Sor
      </button>
    </span>
  );
}

/** The frame's anomalous vehicles as chips; nothing when there are none. */
export function AnomalyChips({ imageId, vehicles, max = 6 }: { imageId: string; vehicles: Vehicle[]; max?: number }) {
  const list = anomalous(vehicles).slice(0, max);
  if (!list.length) return null;
  return (
    <div className="vchips" aria-label="Anormal araçlar">
      <span className="vchips-title">Anormal araçlar · sohbete sürükleyin</span>
      <div className="vchips-list">
        {list.map((v) => (
          <VehicleChip key={v.ref} imageId={imageId} v={v} />
        ))}
      </div>
    </div>
  );
}
