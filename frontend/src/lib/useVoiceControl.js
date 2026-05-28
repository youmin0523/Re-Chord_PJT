/**
 * Hands-free transport via Web Speech Recognition.
 *
 *   const voice = useVoiceControl({
 *     onPlay: () => ...,
 *     onPause: () => ...,
 *     onNext: () => ...,
 *     onPrev: () => ...,
 *     onSeek: (sec) => ...,
 *     enabled: true,
 *   });
 *   voice.toggleListening();
 *
 * Korean + English commands supported. Microphone permission is asked
 * once and re-used; we keep the recognizer on a continuous loop so the
 * musician can call "다음", "재생", "스톱" mid-song without remounting.
 *
 * Browsers vary: only Chromium-based (Chrome, Edge, Brave) ship
 * SpeechRecognition reliably. Firefox / Safari often lack it; we expose
 * `supported = false` so the UI can hide the button.
 */

import { useCallback, useEffect, useRef, useState } from "react";


// Command → handler-key + optional argument resolver.
const COMMANDS = [
  { match: /(재생|시작|플레이|play|start)/i,            id: "play" },
  { match: /(일시정지|일시 정지|정지|멈춰|pause|stop)/i, id: "pause" },
  { match: /(다음 곡|다음곡|다음|next song|next)/i,      id: "next" },
  { match: /(이전 곡|이전곡|이전|previous|prev|back)/i,  id: "prev" },
  { match: /(처음|맨처음|reset|from the top)/i,         id: "seek_start" },
  { match: /(5초 앞|forward five|forward 5)/i,          id: "seek_fwd5" },
  { match: /(5초 뒤|back five|back 5)/i,                 id: "seek_back5" },
  { match: /(공연 시작|count in|카운트인|카운트 인)/i,   id: "count_in" },
];


export function useVoiceControl(handlers = {}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [lastCommand, setLastCommand] = useState(null);
  const recognitionRef = useRef(null);

  // Probe support on mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const Sr = window.SpeechRecognition || window.webkitSpeechRecognition;
    setSupported(!!Sr);
  }, []);

  const handleTranscript = useCallback((text) => {
    const lower = String(text || "").trim();
    if (!lower) return;
    for (const cmd of COMMANDS) {
      if (cmd.match.test(lower)) {
        setLastCommand({ id: cmd.id, text: lower, at: Date.now() });
        switch (cmd.id) {
          case "play":       handlers.onPlay?.(); break;
          case "pause":      handlers.onPause?.(); break;
          case "next":       handlers.onNext?.(); break;
          case "prev":       handlers.onPrev?.(); break;
          case "seek_start": handlers.onSeek?.(0); break;
          case "seek_fwd5":  handlers.onSeekDelta?.(+5); break;
          case "seek_back5": handlers.onSeekDelta?.(-5); break;
          case "count_in":   handlers.onCountIn?.(); break;
          default: break;
        }
        return;
      }
    }
  }, [handlers]);

  const start = useCallback(() => {
    if (typeof window === "undefined") return;
    const Sr = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Sr) { setSupported(false); return; }
    if (recognitionRef.current) return;          // already running
    const rec = new Sr();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = "ko-KR";                          // Korean primary; matches still hit English regex
    rec.onresult = (ev) => {
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
        if (ev.results[i].isFinal) handleTranscript(ev.results[i][0].transcript);
      }
    };
    rec.onerror = (ev) => {
      // Common: "no-speech", "audio-capture", "not-allowed". The first two
      // are transient — restart silently. The third needs user action.
      if (ev?.error === "not-allowed") {
        setListening(false);
        recognitionRef.current = null;
      }
    };
    rec.onend = () => {
      // Continuous mode sometimes ends spuriously on Chromium. If we
      // intended to keep listening, restart.
      if (recognitionRef.current === rec) {
        try { rec.start(); } catch { /* ignore — start race */ }
      }
    };
    recognitionRef.current = rec;
    try { rec.start(); setListening(true); }
    catch { setListening(false); recognitionRef.current = null; }
  }, [handleTranscript]);

  const stop = useCallback(() => {
    const rec = recognitionRef.current;
    recognitionRef.current = null;
    if (rec) {
      try { rec.stop(); } catch { /* ignore */ }
    }
    setListening(false);
  }, []);

  const toggleListening = useCallback(() => {
    if (listening) stop(); else start();
  }, [listening, start, stop]);

  // Always clean up on unmount.
  useEffect(() => () => stop(), [stop]);

  return { supported, listening, lastCommand, start, stop, toggleListening };
}
