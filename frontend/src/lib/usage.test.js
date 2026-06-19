import { describe, it, expect, beforeEach } from "vitest";
import {
  summarizeImpact,
  recordKeyRecommended,
  getUsageEvents,
  clearUsage,
  SAVINGS_MIN,
} from "./usage";

const NOW = 1_700_000_000_000;      // fixed clock so windowing is deterministic
const DAY = 86400000;

describe("summarizeImpact", () => {
  it("returns zeros for empty inputs", () => {
    const s = summarizeImpact({}, [], { now: NOW });
    expect(s).toMatchObject({ songs: 0, setlistSongs: 0, keyRecs: 0, minutes: 0, hours: 0 });
  });

  it("sums minutes from songs, key recs and setlist songs using the published assumptions", () => {
    const history = {
      items: [{ id: "a", createdAt: NOW - DAY }, { id: "b", createdAt: NOW - 2 * DAY }],
      setlists: [{ id: "s1", createdAt: NOW - DAY, jobIds: ["a", "b", "c"] }],
    };
    const events = [{ type: "key_recommended", at: NOW - DAY }];
    const s = summarizeImpact(history, events, { sinceDays: 30, now: NOW });

    expect(s.songs).toBe(2);
    expect(s.setlistSongs).toBe(3);
    expect(s.keyRecs).toBe(1);
    const expectedMin =
      2 * SAVINGS_MIN.song_processed +
      1 * SAVINGS_MIN.key_recommended +
      3 * SAVINGS_MIN.setlist_song;
    expect(s.minutes).toBe(expectedMin);
    expect(s.hours).toBe(Math.round((expectedMin / 60) * 10) / 10);
  });

  it("excludes events older than the window", () => {
    const history = {
      items: [{ id: "old", createdAt: NOW - 40 * DAY }, { id: "new", createdAt: NOW - DAY }],
      setlists: [],
    };
    const events = [
      { type: "key_recommended", at: NOW - 40 * DAY },   // outside
      { type: "key_recommended", at: NOW - 2 * DAY },    // inside
    ];
    const s = summarizeImpact(history, events, { sinceDays: 30, now: NOW });
    expect(s.songs).toBe(1);
    expect(s.keyRecs).toBe(1);
  });
});

describe("usage event log", () => {
  beforeEach(() => { localStorage.clear(); clearUsage(); });

  it("records and reads back key-recommendation events", () => {
    expect(getUsageEvents()).toEqual([]);
    recordKeyRecommended(NOW);
    recordKeyRecommended(NOW + 1000);
    const evs = getUsageEvents();
    expect(evs).toHaveLength(2);
    expect(evs[0]).toEqual({ type: "key_recommended", at: NOW });
  });

  it("clearUsage wipes the log", () => {
    recordKeyRecommended(NOW);
    clearUsage();
    expect(getUsageEvents()).toEqual([]);
  });
});
