// The whole symbol vocabulary of the UI. Anything not listed here is written as a word instead.
//   level    ○ DÜŞÜK · ● ORTA · ▲ YÜKSEK · ▲▲ KRİTİK   (shape backs up colour; always shown with the word)
//   verdict  ✓ doğrulandı · ✗ çelişiyor · ? doğrulanamaz · — ilgisiz
//   motion   → open / go on · ← back · ✕ close
// Map symbology is inspired by MIL-STD-2525 / APP-6 (not a compliant implementation): the SHAPE carries
// affiliation, the colour carries our risk level.
//   friendly  → "ÜS" box (the base)
//   unknown   → quatrefoil (every detected vehicle: detection does not make it hostile)
//   pending   → dashed quatrefoil (tracks in the frame the detector did not find)
import { LEVELS, LEVEL_ACTION, LEVEL_ICON, VERDICT_ICON } from "./format";

/** Legend rows, generated from the same maps the badges use. */
export const LEVEL_LEGEND = LEVELS.map((l) => ({ level: l, icon: LEVEL_ICON[l], action: LEVEL_ACTION[l] }));
export const VERDICT_LEGEND = [
  { icon: VERDICT_ICON["DOĞRULANDI"], text: "rapor doğrulandı" },
  { icon: VERDICT_ICON["ÇELİŞİYOR"], text: "rapor kanıtla çelişiyor" },
  { icon: VERDICT_ICON["DOĞRULANAMAZ"], text: "doğrulanamadı" },
];

/** Quatrefoil outline in a -1..21 box: four lobes on the corners of a 6..14 square. */
export const QUATREFOIL = "M6,6 A4.3,4.3 0 1 1 14,6 A4.3,4.3 0 1 1 14,14 A4.3,4.3 0 1 1 6,14 A4.3,4.3 0 1 1 6,6 Z";

export const vehicleSymbol = (label: string) =>
  `<svg class="sym" viewBox="-1 -1 22 22" aria-hidden="true"><path d="${QUATREFOIL}"/></svg><span class="mk-lbl">${label}</span>`;

export const baseSymbol = (name: string) =>
  `<span class="sym-base" aria-hidden="true">ÜS</span><b>${name}</b>`;
