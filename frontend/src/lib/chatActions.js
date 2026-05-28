/**
 * Chat action protocol — bridge between the LLM's natural-language reply
 * and the UI mutations the user wants to apply.
 *
 * Protocol: the assistant may end a reply with a single
 *   <action>{"type": "...", "args": {...}, "label": "..."}</action>
 * block. We extract it, validate the type/args against a strict allowlist
 * here, strip it from the visible content (so the JSON doesn't show in
 * the bubble), and surface a button next to the message. Clicking the
 * button fires a CustomEvent on ``window`` that page-level listeners pick
 * up to mutate local state (PracticePanel) or navigate (Home).
 *
 * Why an allowlist and not arbitrary JSON: a hallucinated ``type`` string
 * shouldn't be invocable. If the LLM invents ``"delete_account"`` we
 * silently drop it — the button never appears.
 */

export const ACTION_EVENT = "rechord:chat-action";

const ALLOWED_LOOP_SECTIONS = new Set([
  "intro", "verse", "pre-chorus", "chorus",
  "post-chorus", "bridge", "instrumental", "solo", "outro",
]);

const ALLOWED_MODES = new Set(["quick_mr", "karaoke", "stems", "pro"]);

/**
 * Validate + normalise. Returns ``null`` for any malformed input so a
 * single bad action never poisons the rest of the response.
 */
function normalize(raw) {
  if (!raw || typeof raw !== "object") return null;
  const type = typeof raw.type === "string" ? raw.type : null;
  // Be forgiving: the model sometimes emits the args fields flat at the
  // top level instead of nested under ``args``. Accept both shapes.
  const nestedArgs = raw.args && typeof raw.args === "object" ? raw.args : {};
  const args = { ...raw, ...nestedArgs };
  delete args.type;
  delete args.label;
  delete args.args;
  const label = typeof raw.label === "string" ? raw.label.trim() : "";
  if (!type) return null;

  if (type === "regenerate") {
    const out = { semitones: 0, tempo_ratio: 1.0 };
    if (Number.isFinite(args.semitones)) {
      out.semitones = Math.max(-12, Math.min(12, Math.round(args.semitones)));
    }
    if (Number.isFinite(args.tempo_ratio)) {
      out.tempo_ratio = Math.max(0.5, Math.min(2.0, Number(args.tempo_ratio)));
    }
    if (typeof args.mode === "string" && ALLOWED_MODES.has(args.mode)) {
      out.mode = args.mode;
    }
    return { type, args: out, label: label || "다시 변환" };
  }

  if (type === "loop_section") {
    const section = typeof args.section === "string" ? args.section.toLowerCase() : null;
    if (!section || !ALLOWED_LOOP_SECTIONS.has(section)) return null;
    return { type, args: { section }, label: label || `${section} 반복` };
  }

  if (type === "stop_loop") {
    return { type, args: {}, label: label || "반복 해제" };
  }

  // Unknown type → reject (anti-hallucination).
  return null;
}

// Action block: <action>{...one-level-balanced JSON...}</action>?
//
// Both the closing </action> tag and a surrounding markdown code fence
// (```json … ```) are optional because real LLM output regularly skips
// one or both. The balanced-brace pattern ``\{(?:[^{}]*|\{[^{}]*\})*\}``
// correctly handles ``{"args": {"semitones": 2}}`` (one level of nesting)
// without a full JSON tokeniser.
const ACTION_BODY = String.raw`\{(?:[^{}]*|\{[^{}]*\})*\}`;
// Eat up to 3 markdown backticks on EACH side of the action so the bubble
// doesn't keep an empty inline-code span where the LLM tried to wrap us.
const ACTION_RE = new RegExp(
  String.raw`\x60{0,3}\s*<action>\s*(${ACTION_BODY})\s*(?:<\/action>)?\s*\x60{0,3}`,
  "gi",
);
// Catch the wider "```json\n<action>…</action>\n```" sandwich so empty
// backticks don't survive in the cleaned bubble text.
const FENCED_ACTION_RE = /```[\w]*\s*<action>[\s\S]*?(?:<\/action>)?\s*```/gi;
// Permissive fallback used only for STRIPPING the bubble — never for
// extraction. Catches malformed/unbalanced <action>…</action> snippets
// so the user doesn't see broken raw JSON in the rendered text.
const LOOSE_ACTION_RE = /<action>[\s\S]*?(?:<\/action>|$)/gi;
// Cleanup: trailing orphan backticks left over when the LLM started a
// fence but skipped the closing one. Two or more in a row at end of text.
const ORPHAN_FENCE_RE = /\s*\x60{2,}\s*$/g;

/**
 * Extract every well-formed action from the assistant content and return
 * ``{ actions, cleaned }`` so the caller can both surface buttons and
 * render the bubble without the raw JSON.
 */
export function parseChatActions(content) {
  const text = content ?? "";
  const actions = [];
  let cleaned = text;
  let match;
  ACTION_RE.lastIndex = 0;
  while ((match = ACTION_RE.exec(text)) !== null) {
    try {
      const parsed = JSON.parse(match[1]);
      const norm = normalize(parsed);
      if (norm) actions.push(norm);
    } catch {
      /* malformed JSON — drop, leave content visible */
    }
  }
  // Strip "```json …<action>…</action>… ```" first so the surrounding
  // backticks don't survive as empty code-fences in the bubble. The
  // ``LOOSE_ACTION_RE`` second pass catches malformed action blocks the
  // strict balanced-brace pattern wouldn't have removed.
  cleaned = cleaned
    .replace(FENCED_ACTION_RE, "")
    .replace(ACTION_RE, "")
    .replace(LOOSE_ACTION_RE, "")
    .replace(ORPHAN_FENCE_RE, "")
    .trim();
  return { actions, cleaned };
}

/**
 * Fire the action onto the window event bus. Page-level listeners
 * (Home, PracticePanel, …) subscribe with ``useEffect`` and react.
 */
export function dispatchChatAction(action) {
  if (!action || !action.type) return;
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(ACTION_EVENT, { detail: action }));
}
