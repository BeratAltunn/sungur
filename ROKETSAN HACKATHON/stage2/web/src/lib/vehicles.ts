// What makes a vehicle worth a question, in the operator's words. Everything is read from the packet's risk
// factors (computed in the backend); this file only names them.
import { dec } from "./format";
import type { Vehicle, VehicleFocus } from "./types";

/** Short labels for a vehicle's anomalies, most urgent first. Empty = nothing unusual. */
export function anomalies(v: Vehicle): string[] {
  const codes = new Set(v.factors.map((f) => f.code));
  const eta = v.kinematics?.eta_min;
  const out: string[] = [];
  if (codes.has("identity_contradicted")) out.push("çelişen kimlik");
  if ((codes.has("eta_short") || codes.has("eta_mid")) && eta != null) out.push(`ETA ~${dec(eta)} dk`);
  else if (codes.has("approaching")) out.push("yaklaşıyor");
  if (codes.has("convoy")) out.push("konvoy");
  if (codes.has("stop_and_go")) out.push("dur-kalk");
  if (codes.has("heavy")) out.push("ağır araç");
  if (codes.has("untracked")) out.push("kayıtsız");
  if (v.promoted) out.push("düşük güven");
  return out;
}

/** Anomalous vehicles of a frame, riskiest first. */
export const anomalous = (vehicles: Vehicle[]) =>
  [...vehicles].filter((v) => anomalies(v).length > 0).sort((a, b) => b.score - a.score);

export const toFocus = (imageId: string, v: Vehicle): VehicleFocus => ({
  image_id: imageId,
  ref: v.ref,
  track_id: v.track_id,
  label: v.label,
});

/** Drag-and-drop payload type (a custom type so only vehicle chips can be dropped on the chat). */
export const DRAG_TYPE = "application/x-nobetci-vehicle";

export function readDrag(dt: DataTransfer): VehicleFocus | null {
  try {
    const raw = dt.getData(DRAG_TYPE);
    return raw ? (JSON.parse(raw) as VehicleFocus) : null;
  } catch {
    return null;
  }
}

/** Put a vehicle into the chat without dragging (button / keyboard). App opens the chat. */
export const focusChat = (f: VehicleFocus) => window.dispatchEvent(new CustomEvent("sentinel:chat-focus", { detail: f }));
