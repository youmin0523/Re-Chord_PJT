import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import {
  Play, Pause, SkipForward, SkipBack, Music2, Guitar,
  Mic2, ListMusic, ArrowLeft, Maximize, Volume2,
  Mic, MicOff, MonitorSmartphone, Cable,
} from "lucide-react";

import { artifactUrl, getChords, getJob, getSections, listSetlists, listNotes } from "@/lib/api";
import { INSTRUMENT_PRESETS, recommendCapo, transposeChord, transposeKey } from "@/lib/transpose";
import { ROLES, ROLE_BY_ID, rootOnly } from "@/lib/roles";
import { formatDuration } from "@/lib/utils";
import { useKeyboardShortcuts } from "@/lib/useKeyboardShortcuts";
import { useVoiceControl } from "@/lib/useVoiceControl";
import { usePerformanceSync } from "@/lib/usePerformanceSync";
import { useMidiInput } from "@/lib/useMidiInput";

/**
 * Band-master live performance view.
 *
 *   /perform/:setlistId  — start of a setlist, auto-advance through jobs
 *   /perform/job/:jobId  — single-song quick-jump
 *
 * Large-text chord chart + section markers + tempo info, instrument
 * transposition selector (concert / Bb trumpet / Eb sax / capo N).
 *
 * Designed for stage use: dark, high-contrast, finger-sized hit zones,
 * spacebar = play/pause, j/l = ±5s, n/p = next/prev section.
 */
export default function PerformanceView() {
  const { t } = useTranslation();
  const { id, setlistId } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();

  // Resolve which jobs are in the queue (setlist or single).
  const [queue, setQueue] = useState([]); // [jobId, ...]
  const [setlistName, setSetlistName] = useState(null);

  useEffect(() => {
    if (id) {
      setQueue([id]);
      setSetlistName(null);
      return;
    }
    if (!setlistId) return;
    listSetlists().then((list) => {
      const s = (list || []).find((x) => x.id === setlistId);
      if (s) {
        setQueue(s.job_ids || []);
        setSetlistName(s.name);
      }
    }).catch(() => {
      // Fall back to localStorage if offline.
      try {
        const local = JSON.parse(localStorage.getItem("rechord:setlists:v1") || "[]");
        const s = local.find((x) => x.id === setlistId);
        if (s) {
          setQueue(s.jobIds || []);
          setSetlistName(s.name);
        }
      } catch { /* ignore */ }
    });
  }, [id, setlistId]);

  const cursorIdx = Math.min(Math.max(0, Number(params.get("i") || 0)), Math.max(0, queue.length - 1));
  const currentJobId = queue[cursorIdx];

  const goPrev = () => setParams({ i: String(Math.max(0, cursorIdx - 1)) });
  const goNext = () => setParams({ i: String(Math.min(queue.length - 1, cursorIdx + 1)) });

  if (!currentJobId) {
    return (
      <main className="min-h-screen flex items-center justify-center text-fg-muted">
        <div className="text-center space-y-2">
          <ListMusic className="size-10 mx-auto opacity-60" />
          <div className="text-sm">{t("perform.empty_setlist")}</div>
          <Link to="/library" className="text-violet hover:underline text-xs">{t("perform.back_to_library")}</Link>
        </div>
      </main>
    );
  }

  return (
    <PerformanceShell
      jobId={currentJobId}
      setlistName={setlistName}
      cursorIdx={cursorIdx}
      total={queue.length}
      onPrev={cursorIdx > 0 ? goPrev : null}
      onNext={cursorIdx < queue.length - 1 ? goNext : null}
      onBack={() => navigate(setlistId ? `/library` : `/job/${currentJobId}`)}
    />
  );
}

function PerformanceShell({ jobId, setlistName, cursorIdx, total, onPrev, onNext, onBack }) {
  const { t } = useTranslation();
  // Embed mode controls layout for the dual-output worship setup:
  //   ?embed=congregation  → giant lyrics/chord readout only (projector view)
  //   ?embed=band          → reserved alias for the default rich layout
  // No param → full band view. Both views share a BroadcastChannel so the
  // congregation window's playhead follows the main window automatically.
  const embed = new URLSearchParams(window.location.search).get("embed");
  const isCongregation = embed === "congregation";

  const [job, setJob] = useState(null);
  const [chords, setChords] = useState(null);
  const [sections, setSections] = useState(null);
  const [notes, setNotes] = useState([]);
  const [preset, setPreset] = useState("concert");
  const [role, setRole] = useState(() => {
    try { return localStorage.getItem("rechord:perform:role") || "leader"; }
    catch { return "leader"; }
  });
  const audioRef = useRef(null);
  const roleCfg = ROLE_BY_ID[role] || ROLE_BY_ID.leader;

  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [countIn, setCountIn] = useState(0);   // 0 = inactive; >0 = beats left
  const countInTimerRef = useRef(null);

  useEffect(() => {
    setJob(null); setChords(null); setSections(null); setNotes([]);
    getJob(jobId).then(setJob).catch(() => {});
    getChords(jobId).then((d) => d?.available && setChords(d)).catch(() => {});
    getSections(jobId).then((d) => d?.available && setSections(d)).catch(() => {});
    listNotes(jobId).then((d) => setNotes(d.notes || [])).catch(() => {});
  }, [jobId]);

  const presetCfg = INSTRUMENT_PRESETS.find((p) => p.id === preset) || INSTRUMENT_PRESETS[0];

  const transposedKey = useMemo(() => {
    if (!job?.meta?.key_name) return null;
    return transposeKey(job.meta.key_name, presetCfg.shift, presetCfg.useFlats);
  }, [job, presetCfg]);

  const chordEvents = useMemo(() => chords?.events || [], [chords]);

  // Cross-window sync — band ↔ congregation view share playhead.
  const sync = usePerformanceSync(jobId, {
    onCommand: (cmd) => {
      const el = audioRef.current;
      if (!el) return;
      if (cmd.type === "play") {
        if (typeof cmd.position === "number") el.currentTime = cmd.position;
        el.play().catch(() => {});
        setPlaying(true);
      } else if (cmd.type === "pause") {
        el.pause();
        setPlaying(false);
      } else if (cmd.type === "seek" && typeof cmd.position === "number") {
        el.currentTime = cmd.position;
      }
    },
  });

  const togglePlay = () => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) {
      el.play();
      setPlaying(true);
      sync.emit({ type: "play", position: el.currentTime });
    } else {
      el.pause();
      setPlaying(false);
      sync.emit({ type: "pause" });
    }
  };

  // Drummer-friendly pre-roll: 1 bar of audible count, then auto-play.
  // Bar length comes from the detected time signature (3 ticks for 3/4,
  // 4 for 4/4, 6 for 6/8 compound, etc.). BPM defaults to 100 if unknown.
  const startWithCountIn = () => {
    if (countIn > 0) return;
    const bpm = Math.max(40, Math.min(220, job?.meta?.bpm || 100));
    const beatSec = 60 / bpm;
    const beatsPerBar = sections?.meter || 4;
    setCountIn(beatsPerBar);
    const tick = (remaining) => {
      // Audible click — generated on-the-fly via Web Audio so we don't need
      // an asset file.
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const ctx = new AudioCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = remaining === 4 ? 1000 : 800;
        gain.gain.value = 0.18;
        osc.connect(gain).connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.04);
      } catch { /* ignore — silent count-in still works */ }
      if (remaining > 1) {
        countInTimerRef.current = setTimeout(() => {
          setCountIn(remaining - 1);
          tick(remaining - 1);
        }, beatSec * 1000);
      } else {
        countInTimerRef.current = setTimeout(() => {
          setCountIn(0);
          const el = audioRef.current;
          if (el) { el.play(); setPlaying(true); }
        }, beatSec * 1000);
      }
    };
    tick(beatsPerBar);
  };

  // Cancel count-in if user presses pause or unmounts.
  useEffect(() => {
    return () => { if (countInTimerRef.current) clearTimeout(countInTimerRef.current); };
  }, []);

  // Wake Lock — keep the screen on during performance so the phone/tablet
  // on a music stand doesn't sleep mid-song. Released automatically on
  // navigation away or visibility loss; re-acquired when the page becomes
  // visible again (Safari/Chrome auto-drop on tab switch).
  useEffect(() => {
    if (!("wakeLock" in navigator)) return;
    let lock = null;
    const acquire = async () => {
      try { lock = await navigator.wakeLock.request("screen"); }
      catch { /* user denied or unsupported — silent */ }
    };
    const onVis = () => {
      if (document.visibilityState === "visible") acquire();
    };
    acquire();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      try { lock?.release(); } catch { /* ignore */ }
    };
  }, []);

  const seek = (delta) => {
    const el = audioRef.current;
    if (!el) return;
    const next = Math.max(0, Math.min(duration, el.currentTime + delta));
    el.currentTime = next;
    sync.emit({ type: "seek", position: next });
  };

  const seekTo = (sec) => {
    const el = audioRef.current;
    if (!el) return;
    const next = Math.max(0, Math.min(duration, sec));
    el.currentTime = next;
    sync.emit({ type: "seek", position: next });
  };

  // Active chord (the one whose [start, end] contains the playhead).
  const activeChordIdx = useMemo(() => {
    for (let i = 0; i < chordEvents.length; i += 1) {
      const c = chordEvents[i];
      if (position >= c.start_sec && position < c.end_sec) return i;
    }
    return -1;
  }, [position, chordEvents]);

  const upcomingChord = chordEvents[activeChordIdx + 1] || null;

  const activeSection = useMemo(() => {
    for (const s of sections?.sections || []) {
      if (position >= s.start_sec && position < s.end_sec) return s;
    }
    return null;
  }, [sections, position]);

  // Capo recommendation when the player is on guitar (capo preset chosen).
  const capoHint = useMemo(() => {
    if (!job?.meta?.key_name) return null;
    if (!/^capo_/.test(preset)) return null;
    return recommendCapo(job.meta.key_name);
  }, [job, preset]);

  // Keyboard shortcuts — performance-tuned.
  useKeyboardShortcuts([
    { combo: "space", handler: togglePlay,           desc: t("perform.shortcut_play_pause") },
    { combo: "c",     handler: startWithCountIn,     desc: t("perform.shortcut_count_in") },
    { combo: "j",     handler: () => seek(-5),       desc: t("perform.shortcut_back5") },
    { combo: "l",     handler: () => seek(+5),       desc: t("perform.shortcut_fwd5") },
    { combo: "n",     handler: () => onNext?.(),     desc: t("perform.shortcut_next_song") },
    { combo: "p",     handler: () => onPrev?.(),     desc: t("perform.shortcut_prev_song") },
  ]);

  // Foot-pedal / Web MIDI control. Default mapping (overrideable later):
  //   Sustain pedal (CC 64) → toggle play/pause on press
  //   Soft pedal (CC 67)    → next song
  //   Program Change ≥ 1    → seek to next section
  // Permission is opt-in via a button in the header.
  const midi = useMidiInput({
    onCC: (cc) => {
      if (cc.controller === 64 && cc.value > 0) togglePlay();
      else if (cc.controller === 67 && cc.value > 0) onNext?.();
    },
    onProgram: () => {
      // Jump to next section if we have one.
      const ss = sections?.sections || [];
      const next = ss.find((s) => s.start_sec > position + 0.1);
      if (next) seekTo(next.start_sec);
    },
  });

  // Hands-free voice control — opt-in via mic button.
  const voice = useVoiceControl({
    onPlay: () => { const el = audioRef.current; if (el && el.paused) { el.play(); setPlaying(true); } },
    onPause: () => { const el = audioRef.current; if (el && !el.paused) { el.pause(); setPlaying(false); } },
    onNext: () => onNext?.(),
    onPrev: () => onPrev?.(),
    onSeek: seekTo,
    onSeekDelta: (d) => seek(d),
    onCountIn: startWithCountIn,
  });

  if (!job) {
    return (
      <main className="min-h-screen flex items-center justify-center text-fg-muted">
        <div className="text-sm">{t("perform.loading_song")}</div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-bg0 text-fg flex flex-col">
      {/* Top bar */}
      <header className="border-b border-white/5 px-3 sm:px-4 py-2 sm:py-3 flex items-center gap-2 sm:gap-3">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center justify-center size-9 rounded-full hover:bg-white/5 text-fg-muted hover:text-fg"
          title={t("perform.exit_title")}
        >
          <ArrowLeft className="size-4" />
        </button>
        <div className="min-w-0">
          <div className="text-[10px] mono uppercase tracking-[0.22em] text-fg-muted">
            {setlistName ? `🎵 ${setlistName}` : "PERFORMANCE"}
          </div>
          <div className="text-sm font-semibold truncate">
            {job.meta?.source_title || job.id}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {total > 1 && (
            <span className="mono text-[11px] text-fg-muted">
              {cursorIdx + 1} / {total}
            </span>
          )}
          {midi.supported && !isCongregation && (
            <button
              type="button"
              onClick={midi.requestPermission}
              title={
                midi.enabled
                  ? t("perform.midi_active", { count: midi.devices.length })
                  : t("perform.midi_inactive")
              }
              className={
                midi.enabled
                  ? "inline-flex items-center justify-center size-8 rounded-full bg-violet/20 text-violet ring-1 ring-violet/40"
                  : "inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted hover:text-fg"
              }
              aria-label={t("perform.midi_aria")}
            >
              <Cable className="size-4" />
            </button>
          )}
          {voice.supported && (
            <button
              type="button"
              onClick={voice.toggleListening}
              title={voice.listening ? t("perform.voice_off") : t("perform.voice_on")}
              className={
                voice.listening
                  ? "inline-flex items-center justify-center size-8 rounded-full bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40 animate-pulseGlow"
                  : "inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted hover:text-fg"
              }
              aria-label={t("perform.voice_aria")}
            >
              {voice.listening ? <Mic className="size-4" /> : <MicOff className="size-4" />}
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              const url = `${window.location.origin}${window.location.pathname}?embed=congregation`;
              window.open(url, "rechord-congregation", "width=1280,height=720,menubar=no,toolbar=no");
            }}
            title={t("perform.open_congregation_title")}
            className="hidden sm:inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted hover:text-fg"
            aria-label={t("perform.open_congregation_aria")}
          >
            <MonitorSmartphone className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => document.documentElement.requestFullscreen?.().catch(() => {})}
            className="inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted hover:text-fg"
            title={t("perform.fullscreen_title")}
          >
            <Maximize className="size-4" />
          </button>
        </div>
      </header>

      {/* Voice-control feedback ribbon — shows the last recognised command. */}
      {voice.listening && voice.lastCommand && (Date.now() - voice.lastCommand.at < 4000) && (
        <div className="px-4 py-1.5 bg-emerald-500/10 text-emerald-200 text-[11px] mono border-b border-emerald-500/20">
          {t("perform.voice_recognised", { text: voice.lastCommand.text, id: voice.lastCommand.id })}
        </div>
      )}

      {/* Hero — key + tempo + section. Collapses to 1col on phones.
          Hidden in congregation embed — projector only needs the chord. */}
      {!isCongregation && (
      <section className="px-3 sm:px-4 py-3 sm:py-5 grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-4 border-b border-white/5">
        <BigStat
          icon={Music2}
          label={t("perform.key_label")}
          value={transposedKey || "—"}
          sub={
            capoHint
              ? t("perform.capo_hint", { capo: capoHint.capo, shape: capoHint.shape })
              : presetCfg.shift !== 0
                ? `concert ${job.meta?.key_name || "—"} · ${presetCfg.shift > 0 ? "+" : ""}${presetCfg.shift} st`
                : "concert pitch"
          }
        />
        <BigStat
          icon={Guitar}
          label={t("perform.bpm_meter")}
          value={
            job.meta?.bpm
              ? `${job.meta.bpm.toFixed(0)} · ${sections?.time_signature || job.meta?.time_signature || "4/4"}`
              : "—"
          }
          sub={activeSection ? activeSection.label : (job.options?.target_bpm || "—")}
        />
        <BigStat
          icon={Mic2}
          label={t("perform.section")}
          value={activeSection ? activeSection.label : "—"}
          sub={duration ? `${formatDuration(position)} / ${formatDuration(duration)}` : "—"}
          accent
        />
      </section>
      )}

      {/* Section quick-jump strip. Tap a section to jump to its start. */}
      {!isCongregation && sections?.sections?.length > 0 && (
        <section className="px-4 py-2 border-b border-white/5 overflow-x-auto">
          <div className="flex items-center gap-1.5 min-w-min">
            {sections.sections.map((s, i) => {
              const isActive = activeSection && s.start_sec === activeSection.start_sec;
              return (
                <button
                  key={`${s.start_sec}-${i}`}
                  type="button"
                  onClick={() => seekTo(s.start_sec)}
                  title={`${s.label} · ${formatDuration(s.start_sec)}`}
                  className={
                    isActive
                      ? "px-2.5 py-1 rounded-md text-[11px] font-semibold bg-cyan/20 text-cyan ring-1 ring-cyan/40 whitespace-nowrap"
                      : "px-2.5 py-1 rounded-md text-[11px] bg-white/5 text-fg-muted hover:text-fg whitespace-nowrap"
                  }
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </section>
      )}

      {/* Notes ribbon — show any time-anchored notes that match the current
          ±10 s window so the band-master sees "watch tempo here" at the right
          moment. */}
      {!isCongregation && notes.filter((n) => n.start_sec != null && Math.abs(n.start_sec - position) < 10).length > 0 && (
        <section className="px-4 py-2 border-b border-white/5 flex items-center gap-2 overflow-x-auto">
          {notes
            .filter((n) => n.start_sec != null && Math.abs(n.start_sec - position) < 10)
            .map((n) => (
              <span
                key={n.id}
                className={
                  n.kind === "warning" ? "px-2 py-0.5 rounded-full text-[10px] bg-amber-400/15 text-amber-300 ring-1 ring-amber-400/30 whitespace-nowrap"
                  : n.kind === "skip" ? "px-2 py-0.5 rounded-full text-[10px] bg-magenta/15 text-magenta ring-1 ring-magenta/30 whitespace-nowrap"
                  : n.kind === "cue" ? "px-2 py-0.5 rounded-full text-[10px] bg-cyan/15 text-cyan ring-1 ring-cyan/30 whitespace-nowrap"
                  : "px-2 py-0.5 rounded-full text-[10px] bg-violet/15 text-violet ring-1 ring-violet/30 whitespace-nowrap"
                }
              >
                {n.text}
              </span>
            ))}
        </section>
      )}

      {/* Role picker — choose which musician's view to show. Persists to
          localStorage so the bandmaster keeps the leader view while the
          drummer keeps the drummer view across page reloads. */}
      {!isCongregation && (
      <section className="px-4 py-2 border-b border-white/5 flex items-center gap-1.5 overflow-x-auto">
        <span className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mr-1 shrink-0">{t("perform.role_label")}</span>
        {ROLES.map((r) => {
          const Icon = r.icon;
          const on = role === r.id;
          return (
            <button
              key={r.id}
              type="button"
              onClick={() => {
                setRole(r.id);
                try { localStorage.setItem("rechord:perform:role", r.id); } catch { /* ignore */ }
              }}
              className={
                on
                  ? "inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] ring-1 ring-cyan/45 bg-cyan/15 text-cyan whitespace-nowrap shrink-0"
                  : "inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] bg-white/5 text-fg-muted hover:text-fg whitespace-nowrap shrink-0"
              }
              title={t(r.labelKey)}
            >
              <Icon className="size-3" />
              {t(r.labelKey)}
            </button>
          );
        })}
      </section>
      )}

      {/* Instrument transposition picker. Scrolls horizontally on phones
          so all 9 presets remain reachable. */}
      {!isCongregation && (
      <section className="px-4 py-3 border-b border-white/5 flex items-center gap-1.5 overflow-x-auto">
        <span className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mr-1 shrink-0">{t("perform.transpose")}</span>
        {INSTRUMENT_PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => setPreset(p.id)}
            className={
              preset === p.id
                ? "px-2.5 py-1 rounded-full text-[11px] ring-1 ring-violet/45 bg-violet/15 text-violet whitespace-nowrap shrink-0"
                : "px-2.5 py-1 rounded-full text-[11px] bg-white/5 text-fg-muted hover:text-fg whitespace-nowrap shrink-0"
            }
          >
            {p.label}
          </button>
        ))}
      </section>
      )}

      {/* Giant chord readout — clamp scales smoothly down to 380 px width */}
      <section className="flex-1 flex flex-col items-center justify-center gap-2 sm:gap-3 px-3 sm:px-4 py-4 sm:py-6 select-none">
        <div className="text-[10px] mono uppercase tracking-[0.22em] text-fg-muted">
          NOW
        </div>
        <motion.div
          key={chordEvents[activeChordIdx]?.label || "—"}
          initial={{ scale: 0.96, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="text-[clamp(64px,18vw,200px)] font-extrabold tracking-tight gradient-text leading-none"
        >
          {chordEvents[activeChordIdx]
            ? transposeChord(chordEvents[activeChordIdx].label, presetCfg.shift, presetCfg.useFlats)
            : (activeSection?.label || "—")}
        </motion.div>
        {upcomingChord && (
          <div className="text-fg-muted mt-1 sm:mt-2 flex flex-wrap items-baseline justify-center gap-1 sm:gap-2">
            <span className="text-[10px] mono uppercase tracking-[0.22em]">NEXT</span>
            <span className="text-xl sm:text-2xl font-semibold">
              {transposeChord(upcomingChord.label, presetCfg.shift, presetCfg.useFlats)}
            </span>
            <span className="text-[10px] sm:text-[11px] mono">
              · {formatDuration(upcomingChord.start_sec - position)} {t("perform.next_in_suffix")}
            </span>
          </div>
        )}
      </section>

      {/* Mini chord ribbon — last 6, current, next 6. Hidden for vocalist
          / drummer (per role.show.chords). Bassist sees root-only labels. */}
      {!isCongregation && roleCfg.show.chords && (
        <section className="px-4 py-3 border-t border-white/5">
          <div className="flex items-center gap-1.5 overflow-x-auto">
            {chordEvents.slice(Math.max(0, activeChordIdx - 6), activeChordIdx + 7).map((c, i) => {
              const isCurrent = (Math.max(0, activeChordIdx - 6) + i) === activeChordIdx;
              const rendered = transposeChord(c.label, presetCfg.shift, presetCfg.useFlats);
              const display = roleCfg.show.root_only ? rootOnly(rendered) : rendered;
              return (
                <span
                  key={`${c.start_sec}-${i}`}
                  className={
                    isCurrent
                      ? "px-3 py-1 rounded-md text-sm font-semibold bg-violet/25 text-violet ring-1 ring-violet/40"
                      : "px-3 py-1 rounded-md text-sm bg-white/5 text-fg-muted"
                  }
                >
                  {display}
                </span>
              );
            })}
          </div>
        </section>
      )}

      {/* Drummer-only: huge bar counter — keeps the drummer locked to the
          structure when the chord ribbon is hidden. */}
      {!isCongregation && roleCfg.show.bar_counter && sections?.beats_sec && (
        <section className="px-4 py-3 border-t border-white/5 flex items-center justify-center gap-6">
          <div className="text-center">
            <div className="text-[10px] mono uppercase tracking-[0.22em] text-fg-muted">BEAT</div>
            <div className="text-3xl font-bold gradient-text mono">
              {(() => {
                const beats = sections.beats_sec || [];
                if (!beats.length) return "—";
                const i = beats.findIndex((b) => b > position);
                const beatIdx = i < 0 ? beats.length : i;
                return ((beatIdx % 4) + 1).toString();
              })()}
              <span className="text-fg-muted text-lg"> /4</span>
            </div>
          </div>
          <div className="text-center">
            <div className="text-[10px] mono uppercase tracking-[0.22em] text-fg-muted">BAR</div>
            <div className="text-3xl font-bold text-fg mono">
              {(() => {
                const dbs = sections.downbeats_sec || [];
                if (!dbs.length) return "—";
                const idx = dbs.findIndex((b) => b > position);
                return (idx < 0 ? dbs.length : idx).toString();
              })()}
            </div>
          </div>
        </section>
      )}

      {/* Count-in overlay — huge centered numbers, drummer-friendly. */}
      {countIn > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg0/90 backdrop-blur-sm pointer-events-none">
          <motion.div
            key={countIn}
            initial={{ scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="text-[clamp(120px,28vw,360px)] font-extrabold gradient-text leading-none"
          >
            {countIn}
          </motion.div>
        </div>
      )}

      {/* Transport — band only. Congregation window is read-only and stays
          in sync via BroadcastChannel from the main band window. */}
      {!isCongregation && (
      <footer className="border-t border-white/5 px-3 sm:px-4 py-3 flex items-center gap-2 sm:gap-3 sticky bottom-0 bg-bg0/95 backdrop-blur">
        <button
          type="button"
          onClick={onPrev}
          disabled={!onPrev}
          className="inline-flex items-center justify-center size-10 rounded-full bg-white/5 hover:bg-white/10 text-fg disabled:opacity-30"
          aria-label={t("perform.prev_song_aria")}
        >
          <SkipBack className="size-4" />
        </button>
        <button
          type="button"
          onClick={togglePlay}
          className="inline-flex items-center justify-center size-14 rounded-full bg-gradient-to-br from-violet to-magenta text-white hover:shadow-[0_10px_30px_-12px_rgba(139,92,246,0.7)]"
          aria-label={playing ? t("perform.pause_aria") : t("perform.play_aria")}
        >
          {playing ? <Pause className="size-5" /> : <Play className="size-5 ml-0.5" />}
        </button>
        <button
          type="button"
          onClick={startWithCountIn}
          disabled={countIn > 0 || playing}
          title={t("perform.count_in_title")}
          className="hidden sm:inline-flex items-center justify-center size-10 rounded-full bg-cyan/15 hover:bg-cyan/25 text-cyan ring-1 ring-cyan/30 disabled:opacity-40"
        >
          <span className="mono text-[11px] font-bold">1·2·3</span>
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!onNext}
          className="inline-flex items-center justify-center size-10 rounded-full bg-white/5 hover:bg-white/10 text-fg disabled:opacity-30"
          aria-label={t("perform.next_song_aria")}
        >
          <SkipForward className="size-4" />
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(duration, 0.01)}
          step={0.01}
          value={Math.min(position, duration || 0)}
          onChange={(e) => {
            const t = Number(e.target.value);
            const el = audioRef.current;
            if (el) el.currentTime = t;
            setPosition(t);
          }}
          className="flex-1 accent-violet"
          aria-label={t("perform.seek_aria")}
        />
        <Volume2 className="size-4 text-fg-muted" />
        <span className="mono text-[11px] text-fg-muted">
          {formatDuration(position)} / {formatDuration(duration)}
        </span>
      </footer>
      )}

      {/* Hidden audio element. Source switches per role: drummer prefers
          the monitor track (click + voice cues) when one is available,
          everyone else uses the polished instrumental. */}
      <audio
        ref={audioRef}
        src={artifactUrl(
          jobId,
          // Try the role's preferred artifact, fall back to instrumental.
          job.artifacts?.[roleCfg.audio] ? roleCfg.audio : "instrumental_final",
        )}
        preload="metadata"
        onTimeUpdate={(e) => setPosition(e.target.currentTime || 0)}
        onLoadedMetadata={(e) => setDuration(e.target.duration || 0)}
        onEnded={() => { setPlaying(false); onNext?.(); }}
      />
    </main>
  );
}

function BigStat({ icon: Icon, label, value, sub, accent }) {
  return (
    <div className="rounded-xl bg-white/[0.025] ring-1 ring-white/5 p-3 sm:p-4">
      <div className="flex items-center gap-2 text-[10px] mono uppercase tracking-[0.18em] text-fg-muted">
        <Icon className="size-3" /> {label}
      </div>
      <div className={accent ? "text-xl sm:text-2xl font-bold gradient-text mt-1" : "text-xl sm:text-2xl font-bold text-fg mt-1"}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-fg-muted mt-0.5 truncate" title={typeof sub === "string" ? sub : undefined}>{sub}</div>}
    </div>
  );
}
