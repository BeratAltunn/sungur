// Display helpers only. Evidence numbers come from the backend; these just format them (decimal comma).
import type { Label, Level, VerdictT } from "./types";

export const dec = (x: number, nd = 1) => x.toFixed(nd).replace(".", ",");
export const km = (m: number, nd = 1) => `${dec(m / 1000, nd)} km`;
/** The user asked for less motion: map fly-tos and smooth scrolls become instant. */
export const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
export const smooth = (): ScrollBehavior => (reducedMotion() ? "auto" : "smooth");
export const flyMs = (ms: number) => (reducedMotion() ? 0 : ms);

/** Duration for people: 48 sn · 2,3 dk. */
export const secs = (s: number) => (s < 90 ? `${Math.round(s)} sn` : `${dec(s / 60)} dk`);
export const hhmm = (t: number) => {
  const r = Math.round(t);
  return `${String(Math.floor(r / 60)).padStart(2, "0")}:${String(r % 60).padStart(2, "0")}`;
};

export const LEVELS: Level[] = ["KRİTİK", "YÜKSEK", "ORTA", "DÜŞÜK"];
export const LEVEL_ICON: Record<Level, string> = { "DÜŞÜK": "○", ORTA: "●", "YÜKSEK": "▲", "KRİTİK": "▲▲" };
export const LEVEL_CLASS: Record<Level, string> = {
  "DÜŞÜK": "lv-low",
  ORTA: "lv-mid",
  "YÜKSEK": "lv-high",
  "KRİTİK": "lv-crit",
};
/** Astro UXDS status colours (off / caution / serious / critical) for map strokes and image boxes. */
export const LEVEL_COLOR: Record<Level, string> = {
  "DÜŞÜK": "#a4abb6",
  ORTA: "#fce83a",
  "YÜKSEK": "#ffb302",
  "KRİTİK": "#ff3838",
};
export const LEVEL_ACTION: Record<Level, string> = {
  "DÜŞÜK": "Sonraki turda bakılır",
  ORTA: "İzlemeye al, teyit sor",
  "YÜKSEK": "Amire bildir",
  "KRİTİK": "Anında eskalasyon",
};

export const VERDICT_ICON: Record<VerdictT, string> = {
  "DOĞRULANDI": "✓",
  "ÇELİŞİYOR": "✗",
  "DOĞRULANAMAZ": "?",
  "İLGİSİZ": "—",
};
export const VERDICT_CLASS: Record<VerdictT, string> = {
  "DOĞRULANDI": "vd-ok",
  "ÇELİŞİYOR": "vd-bad",
  "DOĞRULANAMAZ": "vd-unk",
  "İLGİSİZ": "vd-irr",
};

export const LABEL_TR: Record<Label, string> = {
  car: "otomobil",
  van: "panelvan",
  truck: "kamyon",
  bus: "otobüs",
  unknown: "araç",
};

export const SOURCE_TR = { official: "resmî", third_party: "3. taraf" } as const;

export const DECISION_TR = { approve: "onaylandı", override: "seviye değişti", escalate: "amire iletildi", undo: "geri alındı" } as const;
export const DECISION_ICON = { approve: "✓", override: "⇄", escalate: "↑", undo: "↺" } as const;

const ZONE_DISPLAY: Record<string, string> = {
  "Kuzey Yolu": "Kuzey Yolu",
  "Kuzeydogu Kavsagi": "Kuzeydoğu Kavşağı",
  "Dogu Yolu": "Doğu Yolu",
  "Guneydogu Yerlesimi": "Güneydoğu Yerleşimi",
  "Guney Kapisi Yaklasimi": "Güney Kapısı Yaklaşımı",
  "Guneybati Yolu": "Güneybatı Yolu",
  "Bati Yerlesimi": "Batı Yerleşimi",
  "Kuzeybati Yolu": "Kuzeybatı Yolu",
};
export const zoneName = (z: string) => ZONE_DISPLAY[z] ?? z;

export const STEP_TR: Record<string, string> = {
  "1_tespit": "1 · Tespit",
  "2_koordinat": "2 · Koordinat",
  "3_eşleme_kinematik": "3 · Eşleme ve kinematik",
  "4_raporlar": "4 · Rapor doğrulama",
  "5_risk": "5 · Risk",
  "6_llm_analist_1": "6 · LLM analist",
  "6_llm_analist_2": "6b · LLM düzeltme turu",
  "6_llm_önbellek": "6 · LLM analist (önbellekten)",
  "6_şablon_brief": "6 · Kural tabanlı brief",
};

/** Split a text into plain parts and evidence ids (V1, T0122, R069) so they can become chips. */
export function splitRefs(text: string): { t: string; ref?: string }[] {
  const out: { t: string; ref?: string }[] = [];
  const re = /\b(img_\d+|[VTR]\d{1,4})\b/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push({ t: text.slice(last, m.index) });
    out.push({ t: m[1], ref: m[1] });
    last = m.index! + m[1].length;
  }
  if (last < text.length) out.push({ t: text.slice(last) });
  return out;
}

export const storage = {
  get<T>(key: string, fallback: T): T {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : (JSON.parse(v) as T);
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* private mode */
    }
  },
};
