import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ACTION_EVENT } from "@/lib/chatActions";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import {
  Music2,
  FileAudio,
  Sparkles as PolishIcon,
  Headphones,
  Music3 as ScoreIcon,
  ArrowRight,
  HelpCircle,
  Cpu,
  RotateCw,
} from "lucide-react";

import { ModeSelector } from "@/components/ModeSelector";
import { Uploader } from "@/components/Uploader";
import { UrlInput } from "@/components/UrlInput";
import { AccuracyGuide } from "@/components/AccuracyGuide";
import { KeyControl } from "@/components/KeyControl";
import { TempoControl } from "@/components/TempoControl";
import { FormatPicker } from "@/components/FormatPicker";
import { Disclosure } from "@/components/ui/Disclosure";
import { OnboardingTour } from "@/components/OnboardingTour";
import { Glossary } from "@/components/ui/Tooltip";
import { createJob } from "@/lib/api";

const DEFAULT_MODELS = {
  quick_mr: ["mdx23c_instvoc_hq"],
  karaoke: ["mdx23c_instvoc_hq", "bs_roformer_1297", "htdemucs_ft", "melband_kim_inst_v2"],
  stems: ["htdemucs_6s"],
  pro: ["melband_kim_ft2_bleedless", "mdx23c_instvoc_hq", "bs_roformer_1297", "htdemucs_ft", "melband_kim_inst_v2"],
};

// All separation models the platform knows about. Aliases are matched
// against backend MODELS dict (some require fetch_sota_separator.py to
// have downloaded the weights — those entries note SOTA).
// ``noteKey`` maps to home.models.note_* in the i18n bundle so the badge
// text follows the active locale. ``note`` (literal) is used when no key
// applies — model-specific tags like "4-stem ft" stay universal.
const ALL_SEPARATOR_MODELS = [
  { id: "mdx23c_instvoc_hq",               label: "MDX23C InstVoc HQ",                bundled: true,  noteKey: "note_default" },
  { id: "bs_roformer_1297",                label: "BS-Roformer 1297",                  bundled: true,  noteKey: "note_default" },
  { id: "htdemucs_ft",                     label: "htdemucs_ft",                       bundled: true,  note: "4-stem ft" },
  { id: "htdemucs_6s",                     label: "htdemucs_6s",                       bundled: true,  note: "6-stem" },
  { id: "melband_kim_inst_v2",             label: "MelBand Kim Inst v2",               bundled: true,  noteKey: "note_default" },
  { id: "melband_roformer_kim",            label: "MelBandRoformer Kim (canonical)",   bundled: false, noteKey: "note_sota" },
  { id: "bs_roformer_hyperace_v2_inst",    label: "BS-Roformer HyperACE v2 (inst)",    bundled: false, noteKey: "note_sota_generic" },
  { id: "bs_roformer_hyperace_v2_voc",     label: "BS-Roformer HyperACE v2 (voc)",     bundled: false, noteKey: "note_sota_generic" },
  { id: "bs_roformer_large_inst_v2",       label: "BS-Roformer Large (inst)",          bundled: false, noteKey: "note_sota_large" },
  { id: "bs_roformer_anvuew_ft1",          label: "BS-Roformer anvuew ft1",            bundled: false, note: "SDR 12.55" },
  { id: "melband_roformer_4stem_ft_large", label: "MelBand 4-stem ft Large",           bundled: false, note: "4-stem ft" },
  { id: "mdx23c_instvoc_hq_2_live",        label: "MDX23C InstVoc HQ v2",              bundled: false, note: "" },
];

// Meter / time-signature IDs are universal; only the "auto" label varies.
const METER_OPTIONS = [
  { id: "auto", labelKey: "lang.auto" },
  { id: "2",    label: "2/4" },
  { id: "3",    label: "3/4" },
  { id: "4",    label: "4/4" },
  { id: "5",    label: "5/4" },
  { id: "6",    label: "6/8" },
  { id: "7",    label: "7/8" },
  { id: "8",    label: "8/8" },
  { id: "9",    label: "9/8" },
  { id: "12",   label: "12/8" },
];

// The two "headline" presets shown as cards. Other styles live in the
// per-stem dropdown below. ``labelKey`` / ``hintKey`` resolve via t().
const SCORE_STYLE_OPTIONS = [
  { id: "lead_sheet",  labelKey: "notation.lead_sheet_short",  hintKey: "notation.lead_sheet_hint" },
  { id: "grand_staff", labelKey: "notation.grand_staff_short", hintKey: "notation.grand_staff_hint" },
];

// Full vocabulary the backend supports.
const ALL_NOTATION_STYLES = [
  { id: "lead_sheet",    labelKey: "notation.lead_sheet_full" },
  { id: "grand_staff",   labelKey: "notation.grand_staff_full" },
  { id: "single_treble", labelKey: "notation.single_treble" },
  { id: "single_bass",   labelKey: "notation.single_bass" },
  { id: "drum",          labelKey: "notation.drum" },
  { id: "guitar_tab",    labelKey: "notation.guitar_tab" },
  { id: "bass_tab",      labelKey: "notation.bass_tab" },
  { id: "choir_satb",    labelKey: "notation.choir_satb" },
];

// Mirrors backend NOTATION_BY_STEM defaults — used to mark "recommended".
const DEFAULT_NOTATION_BY_STEM = {
  vocals: "lead_sheet",
  instrumental: "grand_staff",
  piano: "grand_staff",
  guitar: "guitar_tab",
  bass: "bass_tab",
  drums: "drum",
  other: "grand_staff",
};

export default function Home() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

  // When the user clicks "다시 변환" on a finished Job page, ResultPanel
  // navigates here with `regenerateFrom = { options, sourceTitle }` so we
  // can pre-fill every form control with the previous run's settings.
  // The user still has to re-attach the source file (browsers can't keep
  // the original blob across navigations), so we surface a hint banner.
  const regen = location.state?.regenerateFrom?.options || null;
  const regenSourceTitle = location.state?.regenerateFrom?.sourceTitle || null;

  const [upload, setUpload] = useState(null);
  const [urlValue, setUrlValue] = useState(null);

  const [mode, setMode] = useState(regen?.mode ?? "karaoke");
  const [semitones, setSemitones] = useState(regen?.semitones ?? 0);
  const [tempoRatio, setTempoRatio] = useState(regen?.tempo_ratio ?? 1.0);
  const [format, setFormat] = useState(regen?.format ?? "wav");
  const [sampleRate, setSampleRate] = useState(regen?.sample_rate ?? 48000);
  const [bitDepth, setBitDepth] = useState(regen?.bit_depth ?? "24");

  const [makeScore, setMakeScore] = useState(regen?.make_score ?? false);
  const [scoreStems, setScoreStems] = useState(regen?.score_stems ?? ["vocals"]);
  const [scoreStyle, setScoreStyle] = useState(regen?.score_style ?? "lead_sheet");
  const [scoreStylesPerStem, setScoreStylesPerStem] = useState(regen?.score_styles_per_stem ?? {});

  // Pro mode advanced options.
  const [customModels, setCustomModels] = useState(regen?.models ?? null);
  const [stereoMode, setStereoMode] = useState(regen?.stereo_mode ?? "lr");
  const [applyDiffMask, setApplyDiffMask] = useState(regen?.apply_diff_mask ?? false);
  const [meterOverride, setMeterOverride] = useState(regen?.meter_override ?? "auto");

  // Lyrics
  const [makeLyrics, setMakeLyrics] = useState(regen?.make_lyrics ?? false);
  const [lyricsLang, setLyricsLang] = useState(regen?.lyrics_lang ?? "auto");
  const [lyricsDomain, setLyricsDomain] = useState(regen?.lyrics_domain ?? "");
  const [lyricsModel, setLyricsModel] = useState(regen?.lyrics_model ?? "small");
  const [voiceCues, setVoiceCues] = useState(regen?.voice_cues ?? false);
  const [voiceCueLang, setVoiceCueLang] = useState(regen?.voice_cue_lang ?? "ko");
  const [clickTrack, setClickTrack] = useState(regen?.click_track ?? false);
  const [keepBacking, setKeepBacking] = useState(regen?.keep_backing_vocals ?? false);
  const [polish, setPolish] = useState(regen?.polish ?? true);
  const [polishInstShare, setPolishInstShare] = useState(regen?.polish_inst_share ?? 0.2);
  const [polishReverbTail, setPolishReverbTail] = useState(regen?.polish_reverb_tail ?? false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [showTour, setShowTour] = useState(false);

  // Chatbot action handler — "regenerate" arrives here when the user
  // clicks an "apply" button on a chat message. We merge the requested
  // tweaks into the current form state rather than navigating, so the
  // user can still review before submitting.
  useEffect(() => {
    const onAction = (ev) => {
      const a = ev.detail;
      if (!a || a.type !== "regenerate") return;
      if (Number.isFinite(a.args?.semitones)) setSemitones(a.args.semitones);
      if (Number.isFinite(a.args?.tempo_ratio)) setTempoRatio(a.args.tempo_ratio);
      if (typeof a.args?.mode === "string") setMode(a.args.mode);
      // Surface a brief acknowledgement; reuse the regen banner area if
      // the user is already there, otherwise the form scroll position is
      // their cue.
      try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch { /* noop */ }
    };
    window.addEventListener(ACTION_EVENT, onAction);
    return () => window.removeEventListener(ACTION_EVENT, onAction);
  }, []);

  const sourceReady = !!(upload || urlValue);
  const sourceLabel = upload?.filename || urlValue;
  const showKeyTempo = mode === "karaoke" || mode === "pro";

  const submit = async () => {
    if (!sourceReady) return;
    setError(null);
    setSubmitting(true);
    try {
      const input = upload ? upload.path : urlValue;
      const opts = {
        mode,
        models: customModels && customModels.length > 0 ? customModels : DEFAULT_MODELS[mode],
        ensemble_method: mode === "quick_mr" ? "mean" : "min",
        mixback: false,
        karaoke_postprocess: mode === "karaoke" || mode === "pro",
        semitones,
        tempo_ratio: tempoRatio,
        format,
        sample_rate: sampleRate,
        bit_depth: bitDepth,
        make_score: makeScore,
        score_stems: scoreStems,
        score_style: scoreStyle,
        score_styles_per_stem: Object.fromEntries(
          Object.entries(scoreStylesPerStem).filter(
            ([k, v]) => scoreStems.includes(k) && v && v !== scoreStyle,
          ),
        ),
        make_lyrics: makeLyrics,
        lyrics_lang: lyricsLang,
        lyrics_domain: lyricsDomain,
        lyrics_model: lyricsModel,
        voice_cues: voiceCues,
        voice_cue_lang: voiceCueLang,
        click_track: clickTrack,
        monitor_track: voiceCues || clickTrack,
        keep_backing_vocals: keepBacking,
        polish,
        polish_inst_share: polishInstShare,
        polish_reverb_tail: polishReverbTail,
        stereo_mode: stereoMode,
        apply_diff_mask: applyDiffMask,
        meter: meterOverride,
      };
      const job = await createJob(input, opts);
      navigate(`/job/${job.id}`);
    } catch (e) {
      setError(e.message);
      setSubmitting(false);
    }
  };

  return (
    <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10 lg:py-12 pb-32 space-y-6 sm:space-y-8">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-1.5"
      >
        <div className="flex items-center gap-2 text-[10px] mono uppercase tracking-[0.22em] text-fg-muted">
          <span>
            <Glossary term="AR">{t("home.ar_def")}</Glossary>
            {" → "}
            <Glossary term="MR">{t("home.mr_def")}</Glossary>
          </span>
          <button
            type="button"
            onClick={() => setShowTour(true)}
            className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg normal-case tracking-normal"
            title={t("home.guide")}
          >
            <HelpCircle className="size-3" /> {t("home.guide")}
          </button>
        </div>
        <h1 className="text-2xl sm:text-3xl md:text-4xl font-extrabold tracking-tight leading-tight break-keep">
          <span className="gradient-text">{t("home.hero_title_a")}</span>
          <span className="text-fg">{t("home.hero_title_b")}</span>
        </h1>
        <p className="text-fg-muted text-sm max-w-xl break-keep">
          {t("home.hero_subtitle")}
        </p>
      </motion.div>

      {regen && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          role="status"
          aria-live="polite"
          className="rounded-xl border border-violet/30 bg-violet/10 px-4 py-3 flex items-start gap-3"
        >
          <RotateCw className="size-4 text-violet mt-0.5 shrink-0" aria-hidden="true" />
          <div className="flex-1 min-w-0 text-[12px] text-fg">
            <div className="font-medium">
              {t("home.regen_banner_title", { defaultValue: "이전 변환 설정을 불러왔어요" })}
            </div>
            <div className="text-fg-muted text-[11px] mt-0.5 break-keep">
              {regenSourceTitle
                ? t("home.regen_banner_with_source", {
                    title: regenSourceTitle,
                    defaultValue: "'{{title}}' 의 옵션이 채워졌습니다. 원본 파일이나 URL만 다시 입력하세요.",
                  })
                : t("home.regen_banner_no_source", {
                    defaultValue: "옵션이 그대로 채워졌습니다. 원본 파일이나 URL만 다시 입력하세요.",
                  })}
            </div>
          </div>
        </motion.div>
      )}

      {/* Pre-step accuracy hint: surface missing SOTA deps before the
          user invests minutes into a conversion. Dismissible. */}
      <AccuracyGuide />

      {/* Step 1: source */}
      <Step number={1} title={t("home.step_source")}>
        <UrlInput
          onSubmit={(u) => { setUrlValue(u); setUpload(null); }}
          disabled={submitting}
        />
        <div className="text-center text-[10px] mono uppercase tracking-[0.22em] text-fg-muted/70 py-1">
          {t("common.or", { defaultValue: "또는" })}
        </div>
        <Uploader
          onUploaded={(info) => { setUpload(info); setUrlValue(null); }}
          disabled={submitting}
        />
      </Step>

      {/* Step 2: mode */}
      <Step number={2} title={t("home.step_mode")}>
        <ModeSelector value={mode} onChange={setMode} />
      </Step>

      {/* Step 3: advanced (accordion) */}
      <Step number={3} title={t("home.step_options")} subtitle={t("home.step_options_hint")}>
        <div className="space-y-2.5">
          {showKeyTempo && (
            <Disclosure
              icon={<Music2 className="size-4" />}
              title={t("home.opt_keytempo_title")}
              hint={t("home.opt_keytempo_hint")}
              rightSlot={
                semitones === 0 && tempoRatio === 1
                  ? t("home.opt_keytempo_unchanged")
                  : `${semitones >= 0 ? "+" : ""}${semitones} st · ${Math.round(tempoRatio * 100)}%`
              }
            >
              <div className="grid sm:grid-cols-2 gap-3">
                <KeyControl semitones={semitones} onChange={setSemitones} />
                <TempoControl ratio={tempoRatio} onChangeRatio={setTempoRatio} />
              </div>
            </Disclosure>
          )}

          <Disclosure
            icon={<FileAudio className="size-4" />}
            title={t("home.opt_format_title")}
            hint={t("home.opt_format_hint")}
            rightSlot={`${format.toUpperCase()} · ${sampleRate / 1000}k · ${bitDepth}-bit`}
          >
            <FormatPicker
              format={format}
              sampleRate={sampleRate}
              bitDepth={bitDepth}
              sourceSr={upload?.sample_rate}
              onChange={(n) => {
                setFormat(n.format);
                setSampleRate(n.sampleRate);
                setBitDepth(n.bitDepth);
              }}
            />
          </Disclosure>

          <Disclosure
            icon={<PolishIcon className="size-4" />}
            title={t("home.opt_polish_title")}
            hint={t("home.opt_polish_hint")}
            rightSlot={polish ? `ON · ${Math.round(polishInstShare * 100)}%` : "OFF"}
          >
            <div className="space-y-3">
              <ToggleRow
                title={t("home.polish_amb_title")}
                hint={t("home.polish_amb_hint")}
                value={polish}
                onChange={setPolish}
                accent="violet"
              />
              {polish && (
                <>
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between mono text-[11px]">
                      <span className="text-fg-muted">{t("home.polish_share_label")}</span>
                      <span className="text-violet">{Math.round(polishInstShare * 100)}%</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={60}
                      step={5}
                      value={Math.round(polishInstShare * 100)}
                      onChange={(e) => setPolishInstShare(Number(e.target.value) / 100)}
                      className="w-full accent-violet"
                    />
                  </div>
                  <ToggleRow
                    title={t("home.polish_reverb_title")}
                    hint={t("home.polish_reverb_hint")}
                    value={polishReverbTail}
                    onChange={setPolishReverbTail}
                    accent="violet"
                  />
                </>
              )}
            </div>
          </Disclosure>

          <Disclosure
            icon={<Headphones className="size-4" />}
            title={t("home.opt_perf_title")}
            hint={t("home.opt_perf_hint")}
            rightSlot={
              [voiceCues && t("home.opt_perf_cue", { defaultValue: "큐" }),
               clickTrack && t("home.opt_perf_click", { defaultValue: "클릭" }),
               keepBacking && t("home.opt_perf_backing", { defaultValue: "백킹" })]
                .filter(Boolean)
                .join(" · ") || "OFF"
            }
          >
            <div className="space-y-2.5">
              <ToggleRow
                title={t("home.perf_cue_title")}
                hint={t("home.perf_cue_hint")}
                value={voiceCues}
                onChange={setVoiceCues}
                accent="cyan"
              />
              {voiceCues && (
                <div className="pl-2 flex items-center gap-2">
                  {[
                    { id: "ko", labelKey: "lang.ko" },
                    { id: "en", labelKey: "lang.en" },
                  ].map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      onClick={() => setVoiceCueLang(l.id)}
                      className={
                        voiceCueLang === l.id
                          ? "px-3 py-1 rounded-full text-xs ring-1 ring-cyan/40 bg-cyan/15 text-cyan"
                          : "px-3 py-1 rounded-full text-xs bg-white/5 text-fg-muted hover:text-fg"
                      }
                    >
                      {t(l.labelKey)}
                    </button>
                  ))}
                </div>
              )}
              <ToggleRow
                title={t("home.perf_click_title")}
                hint={t("home.perf_click_hint")}
                value={clickTrack}
                onChange={setClickTrack}
                accent="cyan"
              />
              <ToggleRow
                title={t("home.perf_backing_title")}
                hint={t("home.perf_backing_hint")}
                value={keepBacking}
                onChange={setKeepBacking}
                accent="cyan"
              />
            </div>
          </Disclosure>

          <Disclosure
            icon={<ScoreIcon className="size-4" />}
            title={t("home.opt_score_title")}
            hint={t("home.opt_score_hint")}
            rightSlot={makeScore ? `ON · ${scoreStems.length} stem · ${scoreStyle === "grand_staff" ? "grand" : scoreStyle === "drum" ? "drum" : scoreStyle === "guitar_tab" ? "gtr-tab" : scoreStyle === "bass_tab" ? "bs-tab" : scoreStyle === "choir_satb" ? "SATB" : "lead"}` : "OFF"}
          >
            <ToggleRow
              title={t("home.score_toggle_title")}
              hint={t("home.score_toggle_hint")}
              value={makeScore}
              onChange={setMakeScore}
              accent="violet"
            />
            {makeScore && (
              <div className="pt-3 space-y-3">
                <div>
                  <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">
                    {t("home.score_default_style")}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {SCORE_STYLE_OPTIONS.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => setScoreStyle(s.id)}
                        className={
                          scoreStyle === s.id
                            ? "text-left rounded-lg px-3 py-2 ring-1 ring-violet/40 bg-violet/15"
                            : "text-left rounded-lg px-3 py-2 bg-white/5 hover:bg-white/10 ring-1 ring-white/5"
                        }
                      >
                        <div className="text-sm text-fg">{t(s.labelKey)}</div>
                        <div className="text-[10px] text-fg-muted">{t(s.hintKey)}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">
                    {t("home.score_stems_label")}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {["vocals", "instrumental", "piano", "guitar", "bass", "drums", "other"].map((s) => {
                      const on = scoreStems.includes(s);
                      return (
                        <button
                          key={s}
                          type="button"
                          onClick={() => {
                            setScoreStems((prev) =>
                              prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
                            );
                          }}
                          className={
                            on
                              ? "px-3 py-1 rounded-full text-xs ring-1 ring-violet/40 bg-violet/15 text-violet"
                              : "px-3 py-1 rounded-full text-xs bg-white/5 text-fg-muted hover:text-fg"
                          }
                        >
                          {s}
                        </button>
                      );
                    })}
                  </div>
                  <div className="mt-2 text-[10px] text-fg-muted/70">
                    {t("home.score_stems_help")}
                  </div>
                </div>

                {scoreStems.length > 1 && (
                  <div>
                    <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">
                      {t("home.score_per_stem_label")}
                    </div>
                    <div className="space-y-1.5">
                      {scoreStems.map((stem) => {
                        const def = DEFAULT_NOTATION_BY_STEM[stem] || scoreStyle || "lead_sheet";
                        const current = scoreStylesPerStem[stem] || def;
                        return (
                          <div
                            key={stem}
                            className="flex items-center gap-2 rounded-md bg-white/[0.025] ring-1 ring-white/5 px-2.5 py-1.5"
                          >
                            <div className="w-24 mono text-[11px] text-fg-muted">{stem}</div>
                            <select
                              value={current}
                              onChange={(e) =>
                                setScoreStylesPerStem((prev) => ({
                                  ...prev,
                                  [stem]: e.target.value,
                                }))
                              }
                              className="flex-1 bg-black/30 border border-white/10 rounded px-2 py-1 text-[11px] text-fg"
                            >
                              {ALL_NOTATION_STYLES.map((opt) => (
                                <option key={opt.id} value={opt.id}>
                                  {t(opt.labelKey)}
                                  {opt.id === def ? t("home.score_per_stem_recommended") : ""}
                                </option>
                              ))}
                            </select>
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-2 text-[10px] text-fg-muted/70">
                      {t("home.score_per_stem_help")}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Disclosure>

          <Disclosure
            icon={<ScoreIcon className="size-4" />}
            title={t("home.opt_lyrics_title")}
            hint={t("home.opt_lyrics_hint")}
            rightSlot={makeLyrics ? `ON · ${t(`lang.${lyricsLang === "auto" ? "auto" : lyricsLang}`, { defaultValue: lyricsLang })} · ${lyricsDomain ? t(`domain.${lyricsDomain}`) : t("home.lyrics_no_prompt")}` : "OFF"}
          >
            <ToggleRow
              title={t("home.lyrics_toggle_title")}
              hint={t("home.lyrics_toggle_hint")}
              value={makeLyrics}
              onChange={setMakeLyrics}
              accent="cyan"
            />
            {makeLyrics && (
              <div className="pt-3 space-y-3">
                <div>
                  <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">
                    {t("home.lyrics_language_label")}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      { id: "auto", labelKey: "lang.auto" },
                      { id: "ko",   labelKey: "lang.ko" },
                      { id: "en",   labelKey: "lang.en" },
                      { id: "ja",   labelKey: "lang.ja" },
                      { id: "zh",   labelKey: "lang.zh" },
                    ].map((l) => (
                      <button
                        key={l.id}
                        type="button"
                        onClick={() => setLyricsLang(l.id)}
                        className={
                          lyricsLang === l.id
                            ? "px-3 py-1 rounded-full text-xs ring-1 ring-cyan/40 bg-cyan/15 text-cyan"
                            : "px-3 py-1 rounded-full text-xs bg-white/5 text-fg-muted hover:text-fg"
                        }
                      >
                        {t(l.labelKey)}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">
                    {t("home.lyrics_domain_label")}
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                    {[
                      { id: "",            labelKey: "domain.none" },
                      { id: "worship_ko",  labelKey: "domain.worship_ko" },
                      { id: "worship_en",  labelKey: "domain.worship_en" },
                      { id: "kpop_ko",     labelKey: "domain.kpop_ko" },
                      { id: "ballad_ko",   labelKey: "domain.ballad_ko" },
                      { id: "jazz_en",     labelKey: "domain.jazz_en" },
                    ].map((d) => (
                      <button
                        key={d.id || "_"}
                        type="button"
                        onClick={() => setLyricsDomain(d.id)}
                        className={
                          lyricsDomain === d.id
                            ? "px-2.5 py-1.5 rounded-md text-[11px] ring-1 ring-cyan/40 bg-cyan/15 text-cyan"
                            : "px-2.5 py-1.5 rounded-md text-[11px] bg-white/5 text-fg-muted hover:text-fg"
                        }
                      >
                        {t(d.labelKey)}
                      </button>
                    ))}
                  </div>
                  <div className="mt-2 text-[10px] text-fg-muted/70">
                    {t("home.lyrics_domain_help1")} {t("home.lyrics_domain_help2")}
                  </div>
                </div>

                <div>
                  <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">
                    {t("home.lyrics_model_label")}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      { id: "small",    labelKey: "whisper.small" },
                      { id: "medium",   labelKey: "whisper.medium" },
                      { id: "large-v3", labelKey: "whisper.large_v3" },
                    ].map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => setLyricsModel(m.id)}
                        className={
                          lyricsModel === m.id
                            ? "px-3 py-1 rounded-full text-xs ring-1 ring-cyan/40 bg-cyan/15 text-cyan"
                            : "px-3 py-1 rounded-full text-xs bg-white/5 text-fg-muted hover:text-fg"
                        }
                      >
                        {t(m.labelKey)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </Disclosure>

          {/* Pro mode advanced options — only meaningful on `pro`. */}
          {mode === "pro" && (
            <Disclosure
              icon={<Cpu className="size-4" />}
              title={t("home.pro_title")}
              hint={t("home.pro_hint")}
              rightSlot={
                [
                  customModels?.length ? t("home.pro_models_count", { count: customModels.length }) : null,
                  stereoMode === "mid_side" ? "mid/side" : null,
                  applyDiffMask ? "diff-mask" : null,
                  meterOverride !== "auto" ? meterOverride : null,
                ].filter(Boolean).join(" · ") || t("home.pro_default_label")
              }
            >
              <div className="space-y-3">
                <div>
                  <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">
                    {t("home.pro_models_label")}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                    {ALL_SEPARATOR_MODELS.map((m) => {
                      const current = customModels ?? DEFAULT_MODELS.pro;
                      const on = current.includes(m.id);
                      const noteText = m.noteKey ? t(`models.${m.noteKey}`) : (m.note || "");
                      return (
                        <label
                          key={m.id}
                          className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-white/[0.03] cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => {
                              const cur = customModels ?? DEFAULT_MODELS.pro;
                              const next = on
                                ? cur.filter((x) => x !== m.id)
                                : [...cur, m.id];
                              setCustomModels(next);
                            }}
                            className="accent-violet"
                          />
                          <span className="text-[12px] text-fg flex-1 truncate" title={m.label}>
                            {m.label}
                          </span>
                          <span className="mono text-[9px] text-fg-muted/70 shrink-0">
                            {m.bundled ? t("models.note_default") : (noteText || t("models.note_sota_generic"))}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                  <div className="mt-1 text-[10px] text-fg-muted/70">
                    {t("home.pro_models_help")}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-1.5">
                      {t("home.pro_stereo_label")}
                    </div>
                    <div className="flex gap-1">
                      {[
                        { id: "lr",       labelKey: "stereo.lr" },
                        { id: "mid_side", labelKey: "stereo.ms" },
                      ].map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => setStereoMode(s.id)}
                          className={
                            stereoMode === s.id
                              ? "px-2.5 py-1 rounded-full text-[11px] ring-1 ring-violet/40 bg-violet/15 text-violet"
                              : "px-2.5 py-1 rounded-full text-[11px] bg-white/5 text-fg-muted hover:text-fg"
                          }
                        >
                          {t(s.labelKey)}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-1.5">
                      {t("home.pro_meter_label")}
                    </div>
                    <select
                      value={meterOverride}
                      onChange={(e) => setMeterOverride(e.target.value)}
                      className="w-full bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 text-[12px] mono"
                    >
                      {METER_OPTIONS.map((m) => (
                        <option key={m.id} value={m.id}>{m.labelKey ? t(m.labelKey) : m.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <ToggleRow
                  title={t("home.pro_diff_title")}
                  hint={t("home.pro_diff_hint")}
                  value={applyDiffMask}
                  onChange={setApplyDiffMask}
                  accent="violet"
                />
              </div>
            </Disclosure>
          )}
        </div>
      </Step>

      {error && (
        <div className="rounded-xl p-3 text-sm bg-rose-500/10 text-rose-200 border border-rose-500/20">
          {error}
        </div>
      )}

      {/* Sticky CTA bar */}
      <StickyCTA
        ready={sourceReady}
        submitting={submitting}
        sourceLabel={sourceLabel}
        mode={mode}
        onSubmit={submit}
      />

      {/* First-run + manual-trigger onboarding */}
      <OnboardingTour force={showTour} onClose={() => setShowTour(false)} />
    </main>
  );
}

function Step({ number, title, subtitle, children }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="mono text-[10px] uppercase tracking-[0.22em] text-fg-muted/70">
          STEP {number}
        </span>
        <h2 className="text-sm sm:text-base font-semibold text-fg">{title}</h2>
        {subtitle && (
          <span className="text-[11px] text-fg-muted basis-full sm:basis-auto">{subtitle}</span>
        )}
      </div>
      {children}
    </section>
  );
}

function ToggleRow({ title, hint, value, onChange, accent = "violet" }) {
  const ringMap = {
    violet: "checked:bg-violet checked:border-violet",
    cyan: "checked:bg-cyan checked:border-cyan",
  };
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer rounded-lg px-2 py-1.5 hover:bg-white/[0.03]">
      <div className="min-w-0">
        <div className="text-sm text-fg leading-snug">{title}</div>
        <div className="text-[11px] text-fg-muted leading-snug">{hint}</div>
      </div>
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className={`appearance-none size-5 rounded-md border border-white/15 bg-white/5 transition-colors ${ringMap[accent]}`}
      />
    </label>
  );
}

function StickyCTA({ ready, submitting, sourceLabel, mode, onSubmit }) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-x-0 bottom-0 z-20 pointer-events-none">
      <div className="max-w-5xl mx-auto px-3 sm:px-6 lg:px-8 pb-3 sm:pb-4 pointer-events-auto"
        style={{ paddingBottom: "calc(0.75rem + env(safe-area-inset-bottom))" }}>
        <div className="glass rounded-2xl px-3 sm:px-4 py-2.5 sm:py-3 flex items-center gap-2 sm:gap-3 shadow-[0_-12px_36px_-20px_rgba(0,0,0,0.6)]">
          <div className="flex-1 min-w-0 text-xs">
            {ready ? (
              <>
                <div className="text-fg-muted text-[10px] sm:text-[11px]">{t("home.cta_ready", { defaultValue: "준비됨" })}</div>
                <div className="text-fg truncate mono text-[11px] sm:text-xs">{sourceLabel}</div>
              </>
            ) : (
              <div className="text-fg-muted text-[11px] sm:text-xs">{t("home.cta_idle", { defaultValue: "URL을 붙이거나 파일을 올려주세요." })}</div>
            )}
          </div>
          <div className="hidden md:inline-flex mono text-[10px] text-fg-muted uppercase tracking-wider px-2 py-1 rounded-md bg-white/5">
            mode: {mode}
          </div>
          <button
            onClick={onSubmit}
            disabled={!ready || submitting}
            className="inline-flex items-center gap-1.5 sm:gap-2 h-10 sm:h-11 px-3.5 sm:px-5 rounded-full text-xs sm:text-sm font-medium bg-gradient-to-br from-violet to-magenta text-white disabled:opacity-30 disabled:cursor-not-allowed hover:shadow-[0_10px_36px_-12px_rgba(139,92,246,0.7)] hover:-translate-y-[1px] transition-all shrink-0"
          >
            {submitting ? t("home.cta_processing") : <>{t("home.cta_start")} <ArrowRight className="size-4" /></>}
          </button>
        </div>
      </div>
    </div>
  );
}
