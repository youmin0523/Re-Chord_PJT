/**
 * Integration test for the setlist "우리 팀 추천 키" wiring: SetlistWarnings
 * fetches each job's meta (mocked), and when a team range is saved + songs
 * carry a vocal melody range, it renders a per-song recommended key.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key, opts) => (opts && opts.defaultValue) || key,
    i18n: { resolvedLanguage: "ko", language: "ko" },
  }),
}));
vi.mock("@/lib/api", () => ({ getJob: vi.fn() }));

import { getJob } from "@/lib/api";
import { SetlistWarnings } from "./SetlistWarnings";
import { saveTeamRange, noteToMidi } from "@/lib/transpose";

function mockTwoSongsWithRange() {
  getJob.mockImplementation((id) =>
    Promise.resolve({
      id,
      input: id,
      meta: {
        source_title: `Song ${id}`,
        key_root: "C",
        key_mode: "major",
        bpm: 120,
        vocals_low_midi: noteToMidi("C4"),
        vocals_high_midi: noteToMidi("C5"),
      },
    }),
  );
}

describe("SetlistWarnings — team key suggestions", () => {
  beforeEach(() => {
    localStorage.clear();
    getJob.mockReset();
  });

  it("renders per-song team key suggestions when a team range is set", async () => {
    saveTeamRange({ low: noteToMidi("A2"), high: noteToMidi("D4") });
    mockTwoSongsWithRange();

    render(<SetlistWarnings setlist={{ id: "s1", jobIds: ["a", "b"] }} />);

    expect(await screen.findByText("우리 팀 추천 키")).toBeInTheDocument();
    expect(await screen.findByText("Song a")).toBeInTheDocument();
    expect(await screen.findByText("Song b")).toBeInTheDocument();
  });

  it("does NOT show the team section when no team range is saved", async () => {
    mockTwoSongsWithRange();

    render(<SetlistWarnings setlist={{ id: "s2", jobIds: ["a", "b"] }} />);

    // Wait until the analysis has rendered (header uses no defaultValue → key).
    await screen.findByText("setlist_warn.header");
    expect(screen.queryByText("우리 팀 추천 키")).not.toBeInTheDocument();
  });
});
