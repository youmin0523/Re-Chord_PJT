/**
 * Vitest smoke for chatActions.
 *
 * The action protocol is the anti-hallucination gate between the LLM's
 * reply and the user's UI. We pin: valid actions parse + strip; unknown
 * action types reject; malformed JSON survives gracefully.
 */

import { describe, expect, it, vi } from "vitest";

import { parseChatActions, dispatchChatAction, ACTION_EVENT } from "./chatActions";

describe("parseChatActions", () => {
  it("returns no actions when the content has none", () => {
    const { actions, cleaned } = parseChatActions("Plain reply, no actions.");
    expect(actions).toEqual([]);
    expect(cleaned).toBe("Plain reply, no actions.");
  });

  it("extracts and normalises a regenerate action", () => {
    const text = '곡 분석 결과... <action>{"type":"regenerate","args":{"semitones":2},"label":"+2로 다시 변환"}</action>';
    const { actions, cleaned } = parseChatActions(text);
    expect(actions).toHaveLength(1);
    expect(actions[0]).toEqual({
      type: "regenerate",
      args: { semitones: 2, tempo_ratio: 1.0 },
      label: "+2로 다시 변환",
    });
    expect(cleaned).toBe("곡 분석 결과...");
  });

  it("clamps semitones to ±12 to defend against hallucinated extremes", () => {
    const text = '<action>{"type":"regenerate","args":{"semitones":42}}</action>';
    const { actions } = parseChatActions(text);
    expect(actions[0].args.semitones).toBe(12);
  });

  it("accepts a known loop_section, rejects unknown ones", () => {
    const valid = '<action>{"type":"loop_section","args":{"section":"chorus"}}</action>';
    const bogus = '<action>{"type":"loop_section","args":{"section":"WAT"}}</action>';
    expect(parseChatActions(valid).actions).toHaveLength(1);
    expect(parseChatActions(bogus).actions).toHaveLength(0);
  });

  it("rejects unknown action types entirely", () => {
    const text = '<action>{"type":"delete_account","args":{}}</action>';
    expect(parseChatActions(text).actions).toHaveLength(0);
  });

  it("survives malformed JSON without crashing", () => {
    const text = "before <action>{not json</action> after";
    const { actions, cleaned } = parseChatActions(text);
    expect(actions).toEqual([]);
    // The malformed tag is stripped anyway so the user doesn't see raw JSON.
    expect(cleaned.trim()).toBe("before  after");
  });

  // Real LLM-misbehaviour regressions observed in live testing.

  it("accepts a flat-args shape the model sometimes emits", () => {
    // Observed: gpt emits "{type, semitones, mode}" without the args wrapper.
    const text = '<action>{"type":"regenerate","semitones":3,"mode":"karaoke"}</action>';
    const { actions } = parseChatActions(text);
    expect(actions).toHaveLength(1);
    expect(actions[0].args.semitones).toBe(3);
    expect(actions[0].args.mode).toBe("karaoke");
  });

  it("tolerates a missing closing </action> tag", () => {
    // Observed: model wraps in markdown backticks and drops the closing tag.
    const text = 'reply\n\n``<action>{"type":"regenerate","args":{"semitones":2}}``';
    const { actions, cleaned } = parseChatActions(text);
    expect(actions).toHaveLength(1);
    expect(actions[0].args.semitones).toBe(2);
    // Backticks shouldn't survive as a visible empty code-span.
    expect(cleaned).not.toMatch(/``$/);
    expect(cleaned).toContain("reply");
  });

  it("strips a full ```json … <action>…</action> … ``` fence", () => {
    const text = 'preamble\n\n```json\n<action>{"type":"stop_loop","args":{}}</action>\n```';
    const { actions, cleaned } = parseChatActions(text);
    expect(actions).toHaveLength(1);
    expect(actions[0].type).toBe("stop_loop");
    expect(cleaned.trim()).toBe("preamble");
  });
});

describe("dispatchChatAction", () => {
  it("fires a CustomEvent on window with the action as detail", () => {
    const spy = vi.fn();
    window.addEventListener(ACTION_EVENT, spy);
    dispatchChatAction({ type: "stop_loop", args: {}, label: "해제" });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0][0].detail).toEqual({
      type: "stop_loop", args: {}, label: "해제",
    });
    window.removeEventListener(ACTION_EVENT, spy);
  });

  it("ignores null / empty actions", () => {
    const spy = vi.fn();
    window.addEventListener(ACTION_EVENT, spy);
    dispatchChatAction(null);
    dispatchChatAction({});
    expect(spy).not.toHaveBeenCalled();
    window.removeEventListener(ACTION_EVENT, spy);
  });
});
