// Chat box completion, entirely in the browser: the vocabulary (GET /api/chat/vocab) is loaded once and every
// key press is matched here. No request per key, no LLM, no cost.
import { LABEL_TR, SOURCE_TR, VERDICT_ICON } from "./format";
import type { ChatVocab, Label, VerdictT } from "./types";

export interface Completion {
  kind: "frame" | "track" | "report" | "vehicle" | "zone" | "time" | "question";
  insert: string; // text that replaces the word being typed (or the whole input for a question)
  label: string;
  hint: string;
  whole?: boolean; // replaces the whole input
}

const TR: Record<string, string> = { ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u", â: "a", î: "i", û: "u" };
/** Case- and diacritic-insensitive form ("Doğu" → "dogu", "İ" → "i"). */
export const norm = (s: string) => s.toLocaleLowerCase("tr").replace(/[çğıöşüâîû]/g, (c) => TR[c] ?? c);

/** The word being typed: from the last space (or start) to the caret. */
export function tokenAt(text: string, caret: number): { start: number; token: string } {
  const before = text.slice(0, caret);
  const m = before.match(/[^\s,;()?!]*$/);
  const token = m ? m[0] : "";
  return { start: caret - token.length, token };
}

const label = (l: Label | null) => (l ? LABEL_TR[l] : "araç");
const verdictText = (v: VerdictT) => `${VERDICT_ICON[v]} ${v.toLocaleLowerCase("tr")}`;

/**
 * Completions for the word at the caret. `frames` are the frames in the chat's context (ranked first; their
 * vehicles complete V-refs and their verdicts are shown on reports). `questions` are the offered questions,
 * completed from the words typed so far.
 */
export function complete(
  text: string,
  caret: number,
  vocab: ChatVocab,
  frames: string[],
  questions: string[],
  max = 6,
): Completion[] {
  const { token } = tokenAt(text, caret);
  const out: Completion[] = [];
  const inCtx = (id: string | null) => (id && frames.includes(id) ? 0 : 1);
  const t = token.toUpperCase();

  if (/^T\d+$/.test(t)) {
    vocab.tracks
      .filter((x) => x.id.startsWith(t))
      .sort((a, b) => inCtx(a.frame) - inCtx(b.frame) || Number(!a.frame) - Number(!b.frame) || a.id.localeCompare(b.id))
      .forEach((x) =>
        out.push({ kind: "track", insert: x.id, label: x.id, hint: x.frame ? `${label(x.label)} · ${x.frame}` : "karede görülmedi" }),
      );
  } else if (/^R\d+$/.test(t)) {
    vocab.reports
      .filter((x) => x.id.startsWith(t))
      .sort((a, b) => inCtx(frames.find((f) => a.verdicts[f]) ?? null) - inCtx(frames.find((f) => b.verdicts[f]) ?? null) || a.id.localeCompare(b.id))
      .forEach((x) => {
        const f = frames.find((id) => x.verdicts[id]);
        const v = f ? ` · ${verdictText(x.verdicts[f])} (${f})` : "";
        out.push({ kind: "report", insert: x.id, label: x.id, hint: `${x.time} · ${SOURCE_TR[x.source]}${v}` });
      });
  } else if (/^V\d*$/.test(t) && frames.length) {
    for (const f of vocab.frames.filter((x) => frames.includes(x.id)))
      for (const v of f.vehicles)
        if (v.ref.startsWith(t))
          out.push({ kind: "vehicle", insert: v.ref, label: v.ref, hint: `${label(v.label)}${v.track ? ` · ${v.track}` : ""} · ${f.id}` });
  } else if (/^IMG_?\d*$/.test(t) || /^\d{3,}$/.test(t)) {
    const digits = t.replace(/^IMG_?/, "");
    vocab.frames
      .filter((x) => x.id.includes(digits))
      .sort((a, b) => inCtx(a.id) - inCtx(b.id))
      .forEach((x) => out.push({ kind: "frame", insert: x.id, label: x.id, hint: `${x.zone} · ${x.time}${x.level ? ` · ${x.level}` : ""}` }));
  } else if (/^\d{1,2}(:\d{0,2})?$/.test(token)) {
    vocab.times.filter((x) => x.startsWith(token)).forEach((x) => out.push({ kind: "time", insert: x, label: x, hint: "saat" }));
  } else if (token.length >= 2) {
    const n = norm(token);
    vocab.zones
      .filter((z) => norm(z).split(" ").some((w) => w.startsWith(n)))
      .forEach((z) => out.push({ kind: "zone", insert: z, label: z, hint: "bölge" }));
  }

  // Offered questions that contain every word typed so far (after at least two words or a long first word).
  const words = norm(text.slice(0, caret)).split(/\s+/).filter(Boolean);
  if (words.length >= 2 || (words.length === 1 && words[0].length >= 4)) {
    for (const q of questions) {
      const qw = norm(q).split(/[\s,;()?]+/);
      if (words.every((w) => qw.some((x) => x.startsWith(w))) && norm(q) !== norm(text.trim()))
        out.push({ kind: "question", insert: q, label: q, hint: "hazır soru", whole: true });
    }
  }
  // An id typed out in full needs no list (Enter should still send the question).
  if (out.length === 1 && !out[0].whole && out[0].insert.toUpperCase() === t) return [];
  return out.slice(0, max);
}

/** Apply a completion: replace the word at the caret (or the whole input for a question). */
export function applyCompletion(text: string, caret: number, c: Completion): { text: string; caret: number } {
  if (c.whole) return { text: c.insert, caret: c.insert.length };
  const { start } = tokenAt(text, caret);
  const next = `${text.slice(0, start)}${c.insert} ${text.slice(caret).replace(/^\s+/, "")}`;
  return { text: next, caret: start + c.insert.length + 1 };
}
