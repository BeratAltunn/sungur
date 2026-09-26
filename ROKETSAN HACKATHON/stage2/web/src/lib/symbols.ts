import type { Label } from "./types";

// Map symbology inspired by MIL-STD-2525 / APP-6 (not a compliant implementation): the frame SHAPE carries
// affiliation, as in the standard; colour carries our risk level (stated in the map legend).
//   friendly  → rectangle (the base)
//   unknown   → quatrefoil (every detected vehicle: detection does not make it hostile)
//   pending   → dashed quatrefoil (tracks in the frame the detector did not find)

/** Quatrefoil outline in a -1..21 box: four lobes on the corners of a 6..14 square. */
const QUATREFOIL = "M6,6 A4.3,4.3 0 1 1 14,6 A4.3,4.3 0 1 1 14,14 A4.3,4.3 0 1 1 6,14 A4.3,4.3 0 1 1 6,6 Z";

export const vehicleSymbol = (label: string) =>
  `<svg class="sym" viewBox="-1 -1 22 22" aria-hidden="true"><path d="${QUATREFOIL}"/></svg><span class="mk-lbl">${label}</span>`;

export const baseSymbol = (name: string) =>
  `<span class="sym-base" aria-hidden="true">ÜS</span><b>${name}</b>`;

/** Side-view silhouettes for the overview map's frame markers (the frame's lead vehicle class, from the backend).
 *  Drawn in currentColor on a 24×14 box; wheels are outlined in the marker background so they read as separate. */
const SILHOUETTE: Record<Label, string> = {
  car: `<path d="M1.5 10.5 V8 L4 7.3 L7 4 H14.5 L18 7.2 L22 8 Q22.8 8.3 22.8 9.2 V10.5 Z"/>`,
  van: `<path d="M1.5 10.5 V3.2 Q1.5 2.5 2.2 2.5 H15.5 L19.5 6.5 L22.2 7.4 Q22.8 7.7 22.8 8.4 V10.5 Z"/>`,
  truck: `<path d="M1 10.5 V1.8 H14 V10.5 Z"/><path d="M15 10.5 V4.5 H19.4 L22.8 8 V10.5 Z"/>`,
  bus: `<path d="M1 10.5 V3.2 Q1 2.2 2 2.2 H21.5 Q22.8 2.2 22.8 3.6 V10.5 Z"/>` +
    `<path class="win" d="M3 4 H6.5 V6.8 H3 Z M8 4 H11.5 V6.8 H8 Z M13 4 H16.5 V6.8 H13 Z M18 4 H21 V6.8 H18 Z"/>`,
  unknown: `<rect class="unk" x="3" y="2.5" width="18" height="8" rx="2.5"/>`,
};
const WHEELS: Record<Label, number[]> = { car: [6, 18], van: [6, 18.5], truck: [4.5, 10.5, 19.5], bus: [5.5, 18.5], unknown: [] };

export const classSymbol = (label: Label, title = "") =>
  `<svg class="veh-sil veh-${label}" viewBox="0 0 24 14" aria-hidden="true">${title ? `<title>${title}</title>` : ""}${SILHOUETTE[label]}` +
  WHEELS[label].map((x) => `<circle class="wheel" cx="${x}" cy="11" r="2.1"/>`).join("") +
  `</svg>`;
