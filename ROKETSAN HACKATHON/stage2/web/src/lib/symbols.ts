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
