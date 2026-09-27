// Colours live only in styles.css (:root). Map layers and SVG attributes need real colour strings, so they read
// the tokens here instead of repeating hex values.
import type { Level } from "./types";

const cache = new Map<string, string>();

/** Value of a CSS custom property on :root, e.g. token("--lv-crit") → "#ff3838". */
export function token(name: string): string {
  let v = cache.get(name);
  if (v === undefined) {
    v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    cache.set(name, v);
  }
  return v;
}

export const LEVEL_VAR: Record<Level, string> = {
  "DÜŞÜK": "--lv-low",
  ORTA: "--lv-mid",
  "YÜKSEK": "--lv-high",
  "KRİTİK": "--lv-crit",
};

/** Risk level colour: the only place a level colour comes from. */
export const levelColor = (l: Level) => token(LEVEL_VAR[l]);
