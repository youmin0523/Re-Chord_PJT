/**
 * Vitest smoke for ConfidenceBadge.
 *
 * What we pin here:
 *   - Renders the percentage when ``showPct`` is true.
 *   - Renders the bucket label when ``showPct`` is false.
 *   - Tooltip / aria-label always carries CONFIDENCE_DISCLAIMER so a
 *     90% reading never reads as "guaranteed correct".
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceBadge, CONFIDENCE_DISCLAIMER } from "./ConfidenceBadge";

describe("ConfidenceBadge", () => {
  it("shows the rounded percentage when showPct", () => {
    render(<ConfidenceBadge value={0.86} />);
    expect(screen.getByText("86%")).toBeInTheDocument();
  });

  it("shows the bucket label when !showPct", () => {
    render(<ConfidenceBadge value={0.42} showPct={false} />);
    // 0.42 → low bucket → "낮음 — 직접 검토 권장"
    expect(screen.getByText(/낮음/)).toBeInTheDocument();
  });

  it("always exposes the disclaimer for screen readers and hover", () => {
    render(<ConfidenceBadge value={0.95} />);
    const badge = screen.getByText("95%").closest("span");
    expect(badge).not.toBeNull();
    // Both attributes must include the disclaimer so neither sighted
    // hover users nor screen-reader users miss it.
    expect(badge.getAttribute("title")).toContain(CONFIDENCE_DISCLAIMER);
    expect(badge.getAttribute("aria-label")).toContain(CONFIDENCE_DISCLAIMER);
  });

  it("treats NaN / undefined as 0%", () => {
    render(<ConfidenceBadge value={undefined} />);
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
});
