/**
 * Vitest unit tests for openProgressSocket — verifies the onStatus
 * callback emits the right transitions, the reconnect loop respects
 * MAX_ATTEMPTS, and terminal events stop reconnect attempts.
 *
 * We mock the global WebSocket with a tiny controllable double; no real
 * network. This is the cheapest way to validate the WS reconnect UI
 * contract (ProgressPanel's amber/rose banner) without spinning up the
 * backend.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";

import { openProgressSocket } from "./api";

class MockWebSocket {
  static instances = [];
  static disableAutoOpen = false;
  static OPEN = 1;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = 0;          // CONNECTING
    MockWebSocket.instances.push(this);
    // Fire onopen on next tick so subscribers get to attach.
    // ``disableAutoOpen`` suppresses this so the retry-exhaustion test
    // can starve the attempt counter (onopen resets it, by design).
    if (!MockWebSocket.disableAutoOpen) {
      queueMicrotask(() => {
        if (this._opened) return;
        this._opened = true;
        this.readyState = MockWebSocket.OPEN;
        this.onopen && this.onopen();
      });
    }
  }

  send() {}
  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose && this.onclose({ code: 1000, reason: "client" });
  }

  // Test helpers
  _drop({ code = 1006, reason = "abnormal" } = {}) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose && this.onclose({ code, reason });
  }
  _emit(data) {
    this.onmessage && this.onmessage({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  MockWebSocket.instances = [];
  MockWebSocket.disableAutoOpen = false;
  globalThis.WebSocket = MockWebSocket;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  delete globalThis.WebSocket;
});

describe("openProgressSocket", () => {
  it("emits connecting then open status on a clean open", async () => {
    const states = [];
    openProgressSocket("job-1", () => {}, null, (s) => states.push(s));
    // Flush the microtask that fires onopen.
    await vi.advanceTimersByTimeAsync(0);
    expect(states).toEqual(["connecting", "open"]);
  });

  it("schedules a reconnect with backoff on unexpected drop", async () => {
    const states = [];
    openProgressSocket("job-2", () => {}, null, (s) => states.push(s));
    await vi.advanceTimersByTimeAsync(0);
    const first = MockWebSocket.instances[0];
    first._drop();

    expect(states).toContain("reconnecting");
    // First retry should fire after 500ms (delay = 500 * 2^0).
    await vi.advanceTimersByTimeAsync(500);
    // A second WebSocket was instantiated for the retry.
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });

  it("stops reconnecting after a terminal 'done' event", async () => {
    const events = [];
    openProgressSocket("job-3", (ev) => events.push(ev), null, () => {});
    await vi.advanceTimersByTimeAsync(0);
    const ws = MockWebSocket.instances[0];
    ws._emit({ type: "done", stage: "done", progress: 1.0 });
    expect(events.at(-1).type).toBe("done");
    ws._drop();
    // Even after advancing past the backoff, no new socket should appear.
    await vi.advanceTimersByTimeAsync(2000);
    expect(MockWebSocket.instances.length).toBe(1);
  });

  it("emits 'failed' after exhausting MAX_ATTEMPTS retries", async () => {
    // Block onopen on every socket so the attempt counter never resets
    // (a successful open is treated as recovery — by design).
    MockWebSocket.disableAutoOpen = true;
    const states = [];
    openProgressSocket("job-4", () => {}, null, (s) => states.push(s));

    // MAX_ATTEMPTS=6 → 6 retries then the 7th drop tips us into "failed".
    // Backoff schedule (capped 8s): 500, 1000, 2000, 4000, 8000, 8000.
    const delays = [500, 1000, 2000, 4000, 8000, 8000];
    for (let i = 0; i < 7; i++) {
      // Each iteration the connector instantiates a fresh MockWebSocket;
      // we drop it immediately so the close handler runs.
      const ws = MockWebSocket.instances[i];
      expect(ws).toBeDefined();
      ws._drop();
      if (i < delays.length) await vi.advanceTimersByTimeAsync(delays[i]);
    }
    expect(states).toContain("failed");
  });

  it("stops reconnecting once .close() is called by the caller", async () => {
    const states = [];
    const ctrl = openProgressSocket("job-5", () => {}, null, (s) => states.push(s));
    await vi.advanceTimersByTimeAsync(0);
    ctrl.close();
    expect(states.at(-1)).toBe("closed");
    // No further retries even after backoff window.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(MockWebSocket.instances.length).toBe(1);
  });
});
