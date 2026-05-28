/**
 * Vitest smoke for EmptyState.
 *
 * The "nothing here yet" card is reused across every empty tab in the
 * Job page; we pin that title/hint render correctly and the optional CTA
 * lands in the document.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Music } from "lucide-react";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders the title and hint", () => {
    render(
      <EmptyState
        icon={Music}
        title="No songs yet"
        hint="Convert your first track to see it here."
      />,
    );
    expect(screen.getByText("No songs yet")).toBeInTheDocument();
    expect(screen.getByText(/Convert your first track/)).toBeInTheDocument();
  });

  it("renders the cta when provided", () => {
    render(
      <EmptyState
        title="Library empty"
        cta={<button type="button">Get started</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Get started" })).toBeInTheDocument();
  });

  it("works with only a title (no icon / illustration)", () => {
    render(<EmptyState title="Minimal" />);
    expect(screen.getByText("Minimal")).toBeInTheDocument();
  });
});
