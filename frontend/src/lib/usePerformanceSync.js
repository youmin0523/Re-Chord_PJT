import { useEffect, useRef, useState } from "react";

/**
 * Cross-window playback sync for the dual-output performance setup.
 *
 *   Main band window → POST  play/pause/seek events to BroadcastChannel
 *   Congregation     → LISTEN and mirror playback state
 *
 * Both windows open the same jobId so they share the audio element source;
 * the channel just synchronises currentTime and play state. BroadcastChannel
 * is same-origin only and ships in every modern browser (Safari 15.4+).
 *
 * Usage:
 *   const sync = usePerformanceSync(jobId, {
 *     onCommand: ({ type, position }) => { ... },     // listener mode
 *   });
 *   sync.emit({ type: "play", position: 12.34 });    // sender mode
 *
 * Both directions are safe — the hook ignores echoes of its own messages.
 */
export function usePerformanceSync(jobId, { onCommand } = {}) {
  const channelRef = useRef(null);
  // Lazy init so Math.random() runs once on mount, not on every render.
  // Strict-mode React rejects impure calls in render bodies; useState's
  // initializer is the documented escape hatch.
  const [senderId] = useState(() => `peer-${Math.random().toString(36).slice(2, 9)}`);

  useEffect(() => {
    if (!jobId || typeof BroadcastChannel === "undefined") return;
    const ch = new BroadcastChannel(`rechord-perform-${jobId}`);
    channelRef.current = ch;
    if (onCommand) {
      ch.onmessage = (evt) => {
        const data = evt.data || {};
        if (data.from === senderId) return;   // ignore self
        onCommand(data);
      };
    }
    return () => {
      try { ch.close(); } catch { /* ignore */ }
      channelRef.current = null;
    };
  }, [jobId, onCommand, senderId]);

  return {
    emit(cmd) {
      const ch = channelRef.current;
      if (!ch) return;
      try {
        ch.postMessage({ ...cmd, from: senderId, t: Date.now() });
      } catch { /* ignore */ }
    },
  };
}
