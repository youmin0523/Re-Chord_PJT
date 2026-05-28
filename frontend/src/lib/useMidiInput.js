import { useEffect, useRef, useState } from "react";

/**
 * Web MIDI input → keyboard-shortcut compatible event bus.
 *
 * Use case: a worship guitar/keys player on stage wants hands-free section
 * advance / play / pause. A USB or Bluetooth foot pedal that sends MIDI
 * Program Change or Control Change messages can drive Re:Chord without
 * the musician touching the screen.
 *
 * The hook does NOT prescribe a mapping — it surfaces a stream of
 * normalised events. The caller decides what each pedal/button does.
 *
 *   const midi = useMidiInput({
 *     onNote: (note) => { if (note.number === 60) play(); },
 *     onCC:   (cc) => { if (cc.controller === 64 && cc.value > 0) next(); },
 *     onProgram: (pc) => { },   // program change
 *   });
 *
 * Returned shape:
 *   { supported, enabled, devices, error, requestPermission, toggle }
 *
 * No permission popup until ``requestPermission()`` is called — Web MIDI
 * is sensitive so we keep it opt-in via a UI button.
 */
export function useMidiInput({ onNote, onCC, onProgram } = {}) {
  const [supported] = useState(() =>
    typeof navigator !== "undefined" && "requestMIDIAccess" in navigator,
  );
  const [enabled, setEnabled] = useState(false);
  const [devices, setDevices] = useState([]);
  const [error, setError] = useState(null);
  const accessRef = useRef(null);
  const callbacksRef = useRef({ onNote, onCC, onProgram });
  // Sync the ref to latest callbacks after render, not during.
  useEffect(() => {
    callbacksRef.current = { onNote, onCC, onProgram };
  }, [onNote, onCC, onProgram]);

  const handleMessage = (evt) => {
    const [status, data1, data2] = evt.data;
    const channel = status & 0x0f;
    const command = status & 0xf0;
    const cb = callbacksRef.current;
    if (command === 0x90 && data2 > 0) {                 // Note On
      cb.onNote?.({ number: data1, velocity: data2, channel });
    } else if (command === 0x80 || (command === 0x90 && data2 === 0)) {
      // Note Off (treated as separate event type if caller needs it).
      cb.onNote?.({ number: data1, velocity: 0, channel, off: true });
    } else if (command === 0xb0) {                       // Control Change
      cb.onCC?.({ controller: data1, value: data2, channel });
    } else if (command === 0xc0) {                       // Program Change
      cb.onProgram?.({ program: data1, channel });
    }
  };

  const refresh = (access) => {
    const inputs = [];
    access.inputs.forEach((inp) => {
      inputs.push({ id: inp.id, name: inp.name, manufacturer: inp.manufacturer });
      inp.onmidimessage = handleMessage;
    });
    setDevices(inputs);
  };

  const requestPermission = async () => {
    if (!supported) {
      setError("이 브라우저는 Web MIDI를 지원하지 않습니다.");
      return false;
    }
    try {
      const access = await navigator.requestMIDIAccess({ sysex: false });
      accessRef.current = access;
      refresh(access);
      access.onstatechange = () => refresh(access);
      setEnabled(true);
      setError(null);
      return true;
    } catch (e) {
      setError(`MIDI 접근 거부됨: ${e?.message || e}`);
      setEnabled(false);
      return false;
    }
  };

  useEffect(() => {
    return () => {
      const a = accessRef.current;
      if (!a) return;
      a.inputs.forEach((inp) => { inp.onmidimessage = null; });
    };
  }, []);

  return { supported, enabled, devices, error, requestPermission };
}
