import { describe, it, expect } from "vitest";
import { recommendSetlistKeys } from "./setlistAnalyzer";
import { noteToMidi } from "./transpose";

const TEAM = { low: noteToMidi("A2"), high: noteToMidi("D4"), label: "우리 팀" };

describe("recommendSetlistKeys", () => {
  it("returns [] when no team range is set", () => {
    expect(recommendSetlistKeys([{ id: "a" }], null)).toEqual([]);
  });

  it("marks songs without a melody range as hasRange:false (no faked key)", () => {
    const out = recommendSetlistKeys(
      [{ id: "a", title: "곡 A", key_root: "C", key_mode: "major" }],
      TEAM,
    );
    expect(out[0]).toMatchObject({ id: "a", hasRange: false, currentKey: "C" });
    expect(out[0].recKey).toBeUndefined();
  });

  it("recommends a transposed key for a song that has a melody range", () => {
    // A high melody (C4–C5) for a low team range → shift down, key drops.
    const out = recommendSetlistKeys(
      [{
        id: "b", title: "곡 B", key_root: "C", key_mode: "major",
        low_midi: noteToMidi("C4"), high_midi: noteToMidi("C5"),
      }],
      TEAM,
    );
    expect(out[0].hasRange).toBe(true);
    expect(out[0].semitones).toBeLessThan(0);
    expect(out[0].recKey).toMatch(/major$/);
    expect(out[0].currentKey).toBe("C");
  });

  it("handles a minor key label and flags an impossible fit", () => {
    const out = recommendSetlistKeys(
      [{
        id: "c", title: "곡 C", key_root: "A", key_mode: "minor",
        low_midi: noteToMidi("C2"), high_midi: noteToMidi("C6"),  // wider than range
      }],
      TEAM,
    );
    expect(out[0].currentKey).toBe("Am");
    expect(out[0].fits).toBe(false);
  });
});
