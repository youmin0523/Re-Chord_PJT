/**
 * Vitest smoke for Tabs.
 *
 * Two layout shapes ship from the same component:
 *   - desktop (>=sm): horizontal tab strip with one panel visible
 *   - mobile (<sm) + mobileLayout="accordion": every panel is a
 *     collapsible section; the default one is open
 *
 * jsdom's matchMedia is stubbed in test/setup.js to return matches=false
 * by default — that means the mobile branch only activates if we ask
 * matchMedia for "(max-width: 639px)" to match. We override per-test.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Tabs } from "./Tabs";

const TABS = [
  { id: "a", label: "First",  content: <div>panel-a</div> },
  { id: "b", label: "Second", content: <div>panel-b</div> },
  { id: "c", label: "Third",  content: <div>panel-c</div> },
];

describe("Tabs", () => {
  describe("horizontal layout (desktop)", () => {
    it("renders only the active panel's content", () => {
      render(<Tabs tabs={TABS} defaultTab="a" />);
      expect(screen.getByText("panel-a")).toBeInTheDocument();
      expect(screen.queryByText("panel-b")).not.toBeInTheDocument();
    });

    it("switches panels when a tab is clicked", () => {
      render(<Tabs tabs={TABS} defaultTab="a" />);
      fireEvent.click(screen.getByRole("tab", { name: "Second" }));
      expect(screen.getByText("panel-b")).toBeInTheDocument();
      expect(screen.queryByText("panel-a")).not.toBeInTheDocument();
    });
  });

  describe("accordion layout (mobile)", () => {
    beforeEach(() => {
      // Force matchMedia to match the mobile breakpoint.
      window.matchMedia = vi.fn().mockImplementation((q) => ({
        matches: q.includes("max-width: 639px"),
        media: q,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }));
    });
    afterEach(() => { delete window.matchMedia; });

    it("renders every tab as a section, default open exposes its content", () => {
      render(<Tabs tabs={TABS} defaultTab="b" mobileLayout="accordion" />);
      // All section headers visible
      expect(screen.getByRole("button", { name: /First/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Second/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Third/ })).toBeInTheDocument();
      // Only the default-open one renders content
      expect(screen.getByText("panel-b")).toBeInTheDocument();
      expect(screen.queryByText("panel-a")).not.toBeInTheDocument();
    });

    it("toggling a closed section reveals its panel without closing the default", () => {
      render(<Tabs tabs={TABS} defaultTab="a" mobileLayout="accordion" />);
      expect(screen.getByText("panel-a")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Third/ }));
      expect(screen.getByText("panel-c")).toBeInTheDocument();
      // 'a' is still open — the accordion supports multiple-open sections
      expect(screen.getByText("panel-a")).toBeInTheDocument();
    });
  });
});
