import { describe, it, expect, beforeEach } from "vitest";
import {
  recommendTranspose,
  loadTeamRange,
  saveTeamRange,
  VOCAL_RANGES,
  noteToMidi,
} from "./transpose";

describe("recommendTranspose", () => {
  const mixed = VOCAL_RANGES.mixed; // D3–D5 → {low:50, high:74}

  it("leaves an already-comfortable melody untouched (0 semitones)", () => {
    // E3–G4 sits well inside D3–D5.
    const rec = recommendTranspose({ lowMidi: 52, highMidi: 67 }, mixed);
    expect(rec.semitones).toBe(0);
    expect(rec.fits).toBe(true);
  });

  it("pulls a too-high melody down until it fits under the ceiling", () => {
    // D4–G5 (62–79) tops out 5 st above the ceiling.
    const rec = recommendTranspose({ lowMidi: 62, highMidi: 79 }, mixed);
    expect(rec.fits).toBe(true);
    expect(rec.hi).toBeLessThanOrEqual(mixed.high);
    expect(rec.lo).toBeGreaterThanOrEqual(mixed.low);
    expect(rec.semitones).toBeLessThan(0);
  });

  it("protects the ceiling over the floor when a melody is wider than the range", () => {
    // C3–G#5 (48–80) is wider than the range — cannot fully fit.
    const rec = recommendTranspose({ lowMidi: 48, highMidi: 80 }, mixed);
    expect(rec.fits).toBe(false);
    // Straining high is worse than mumbling low, so the top is kept inside.
    expect(rec.highOverflow).toBe(0);
    expect(rec.lowOverflow).toBeGreaterThan(0);
  });

  it("returns null on missing inputs", () => {
    expect(recommendTranspose(null, mixed)).toBeNull();
    expect(recommendTranspose({ lowMidi: 60, highMidi: 72 }, null)).toBeNull();
    expect(recommendTranspose({ lowMidi: null, highMidi: 72 }, mixed)).toBeNull();
  });

  it("accepts a custom team range object", () => {
    const team = { low: noteToMidi("A2"), high: noteToMidi("D4"), label: "우리 팀" };
    // A high melody should be pulled down into the team's low range.
    const rec = recommendTranspose({ lowMidi: noteToMidi("C4"), highMidi: noteToMidi("C5") }, team);
    expect(rec.label).toBe("우리 팀");
    expect(rec.hi).toBeLessThanOrEqual(team.high);
  });
});

describe("team range persistence", () => {
  beforeEach(() => localStorage.clear());

  it("round-trips through localStorage", () => {
    expect(loadTeamRange()).toBeNull();
    saveTeamRange({ low: 45, high: 70 });
    expect(loadTeamRange()).toEqual({ low: 45, high: 70, label: "우리 팀" });
  });

  it("clears when passed null", () => {
    saveTeamRange({ low: 45, high: 70 });
    saveTeamRange(null);
    expect(loadTeamRange()).toBeNull();
  });

  it("rejects an inverted range", () => {
    localStorage.setItem("rechord.teamRange.v1", JSON.stringify({ low: 70, high: 45 }));
    expect(loadTeamRange()).toBeNull();
  });
});
