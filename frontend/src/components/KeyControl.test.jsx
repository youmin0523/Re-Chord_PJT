/**
 * Behaviour test for the KeyControl "추천 키" (range-grounded key recommender)
 * and the "우리 팀" custom-range flow. The pure engine is covered in
 * lib/transpose.test.js — here we verify the wiring: button appears, clicking
 * applies the recommended shift, and a team range round-trips to localStorage.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// i18n isn't initialised in the test env — return defaultValue (the Korean
// copy the component ships) so getByRole name matching works.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key, opts) => (opts && opts.defaultValue) || key,
    i18n: { resolvedLanguage: "ko", language: "ko" },
  }),
}));

import { KeyControl } from "./KeyControl";
import { recommendTranspose, VOCAL_RANGES, loadTeamRange, noteToMidi } from "@/lib/transpose";

describe("KeyControl — 추천 키", () => {
  beforeEach(() => localStorage.clear());

  // A melody topping out above the mixed ceiling → recommender shifts down.
  const HIGH_MELODY = { lowMidi: 62, highMidi: 79 };

  it("offers a recommend button and applies the computed shift on click", () => {
    const expected = recommendTranspose(HIGH_MELODY, VOCAL_RANGES.mixed).semitones;
    expect(expected).not.toBe(0);   // sanity: this melody needs transposing

    const onChange = vi.fn();
    render(
      <KeyControl semitones={0} onChange={onChange}
        detectedKey="C major" melodyRange={HIGH_MELODY} />,
    );

    const btn = screen.getByRole("button", { name: /추천 키로 맞추기/ });
    fireEvent.click(btn);
    expect(onChange).toHaveBeenCalledWith(expected);
  });

  it("shows 'applied' state instead of the button when already at the recommended key", () => {
    const expected = recommendTranspose(HIGH_MELODY, VOCAL_RANGES.mixed).semitones;
    render(
      <KeyControl semitones={expected} onChange={vi.fn()}
        detectedKey="C major" melodyRange={HIGH_MELODY} />,
    );
    expect(screen.queryByRole("button", { name: /추천 키로 맞추기/ })).not.toBeInTheDocument();
    expect(screen.getByText(/추천 키 적용됨/)).toBeInTheDocument();
  });

  it("hides the range panel entirely when no melodyRange is known (no faked numbers)", () => {
    render(<KeyControl semitones={0} onChange={vi.fn()} detectedKey="C major" />);
    expect(screen.queryByText("음역 체크")).not.toBeInTheDocument();
  });

  it("saves a custom '우리 팀' range to localStorage and surfaces it as a chip", () => {
    render(
      <KeyControl semitones={0} onChange={vi.fn()}
        detectedKey="C major" melodyRange={HIGH_MELODY} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /\+ 우리 팀/ }));
    fireEvent.click(screen.getByRole("button", { name: /저장/ }));

    expect(loadTeamRange()).toEqual({
      low: noteToMidi("A2"), high: noteToMidi("E5"), label: "우리 팀",
    });
    expect(screen.getByRole("button", { name: "우리 팀" })).toBeInTheDocument();
  });
});
