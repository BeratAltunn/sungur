// Chat context items (vehicles and frames) and what makes a vehicle worth a question, in the operator's words.
// Everything is read from the packet's risk factors (computed in the backend); this file only names them.
import type { DragEvent as ReactDragEvent } from "react";
import { dec } from "./format";
import type { ChatItem, Level, Vehicle } from "./types";

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

export const vehicleItem = (imageId: string, v: Vehicle): ChatItem => ({
  kind: "vehicle",
  image_id: imageId,
  ref: v.ref,
  track_id: v.track_id,
  label: v.label,
});

export const frameItem = (f: { image_id: string; level: Level; zone: string; capture_time: string }): ChatItem => ({
  kind: "frame",
  image_id: f.image_id,
  level: f.level,
  zone: f.zone,
  capture_time: f.capture_time,
});

/** Identity of an item in the context (no duplicates). */
export const itemKey = (c: ChatItem) => (c.kind === "vehicle" ? `v:${c.image_id}:${c.ref}` : `f:${c.image_id}`);

/** The chat can hold this many items; a new one pushes out the oldest. */
export const MAX_CONTEXT = 4;

/** Drag-and-drop payload type (a custom type so only chat items can be dropped on the chat). */
export const DRAG_TYPE = "application/x-nobetci-item";

export function startDrag(e: DragEvent | ReactDragEvent, item: ChatItem) {
  e.dataTransfer?.setData(DRAG_TYPE, JSON.stringify(item));
  e.dataTransfer?.setData("text/plain", item.kind === "vehicle" ? `${item.ref} ${item.track_id ?? ""}`.trim() : item.image_id);
  if (e.dataTransfer) e.dataTransfer.effectAllowed = "copy";
  document.body.classList.add("dragging-item");
}
export const endDrag = () => document.body.classList.remove("dragging-item");

export function readDrag(dt: DataTransfer): ChatItem | null {
  try {
    const raw = dt.getData(DRAG_TYPE);
    return raw ? (JSON.parse(raw) as ChatItem) : null;
  } catch {
    return null;
  }
}

/** Put an item into the chat without dragging (button / keyboard). App adds it and opens the chat. */
export const addToChat = (item: ChatItem) => window.dispatchEvent(new CustomEvent("sentinel:chat-add", { detail: item }));
