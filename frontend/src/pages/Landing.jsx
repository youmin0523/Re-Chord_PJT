import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  Sparkles,
  AudioWaveform,
  Music2,
  Mic2,
  Layers3,
  Headphones,
  Music3,
  Repeat,
  Turtle,
  Hash,
  Check,
  Link2,
  SlidersHorizontal,
  Wand2,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function Landing() {
  return (
    <main>
      <Hero />
      <Features />
      <Workflow />
      <Comparison />
      <Cta />
    </main>
  );
}

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  const { t } = useTranslation();
  return (
    <section className="relative isolate overflow-hidden">
      <Backdrop />
      <div className="relative max-w-6xl mx-auto px-4 sm:px-6 pt-10 pb-16 sm:pt-16 sm:pb-24 md:pt-24 md:pb-32">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="max-w-3xl space-y-5 sm:space-y-6"
        >
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] sm:text-[11px] mono uppercase tracking-[0.18em] sm:tracking-[0.22em] bg-white/5 ring-1 ring-white/10 text-fg-muted">
            <span className="size-1.5 rounded-full bg-emerald-400 animate-pulseGlow" />
            {t("landing.badge")}
          </span>

          <h1 className="text-3xl sm:text-5xl md:text-6xl font-extrabold tracking-tight leading-[1.08]">
            <span className="text-fg">{t("landing.hero_line1")}</span><br />
            <span className="gradient-text">{t("landing.hero_line2")}</span>
          </h1>

          <p className="text-sm sm:text-base md:text-lg text-fg-muted max-w-xl leading-relaxed">
            {t("landing.hero_lead")}
            <span className="text-fg">{t("landing.hero_lead_accent")}</span>
            {t("landing.hero_lead_tail")}
          </p>

          <div className="flex flex-wrap items-center gap-2.5 sm:gap-3 pt-1 sm:pt-2">
            <Link
              to="/app"
              className="inline-flex items-center gap-2 h-11 sm:h-12 px-5 sm:px-6 rounded-full text-sm font-medium bg-gradient-to-br from-violet to-magenta text-white hover:shadow-[0_18px_56px_-18px_rgba(139,92,246,0.7)] hover:-translate-y-[1px] transition-all"
            >
              {t("landing.cta_start")} <ArrowRight className="size-4" />
            </Link>
            <a
              href="#features"
              className="inline-flex items-center gap-1.5 h-11 sm:h-12 px-4 sm:px-5 rounded-full text-sm text-fg-muted hover:text-fg border border-white/10 hover:border-violet/40 transition-colors"
            >
              {t("landing.cta_features")}
            </a>
          </div>

          <div className="pt-4 sm:pt-6 grid grid-cols-1 sm:flex sm:flex-wrap items-start sm:items-center gap-y-1.5 gap-x-6 text-[11px] mono text-fg-muted">
            <Spec label={t("landing.spec_model")} value={t("landing.spec_model_value")} />
            <Spec label={t("landing.spec_engine")} value={t("landing.spec_engine_value")} />
            <Spec label={t("landing.spec_input")} value={t("landing.spec_input_value")} />
          </div>
        </motion.div>

        {/* Faux waveform graphic */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="mt-10 sm:mt-14 hairline rounded-2xl sm:rounded-3xl p-1 bg-gradient-to-br from-violet/10 via-transparent to-cyan/10"
        >
          <div className="glass rounded-[1.1rem] sm:rounded-[1.4rem] p-4 sm:p-6 md:p-8 space-y-4 sm:space-y-5">
            <WaveformShowcase />
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function Spec({ label, value }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-fg-muted/70 uppercase tracking-wider">{label}</span>
      <span className="text-fg">{value}</span>
    </span>
  );
}

// 음악 관련 배경 이미지. 로컬 교체는 /public/landing/ 사용.
// 한 번에 한 장씩 cross-fade로 보입니다.
const HERO_IMAGES = [
  // electric guitarist
  "https://images.unsplash.com/photo-1511735111819-9a3f7709049c?w=2000&auto=format&fit=crop&q=80",
  // mixing console / studio
  "https://images.unsplash.com/photo-1598653222000-6b7b7a552625?w=2000&auto=format&fit=crop&q=80",
  // concert lights / crowd
  "https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=2000&auto=format&fit=crop&q=80",
  // piano keys
  "https://images.unsplash.com/photo-1520523839897-bd0b52f945a0?w=2000&auto=format&fit=crop&q=80",
  // headphones close-up
  "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=2000&auto=format&fit=crop&q=80",
  // vocalist with mic
  "https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?w=2000&auto=format&fit=crop&q=80",
  // drummer on stage
  "https://images.unsplash.com/photo-1519892300165-cb5542fb47c7?w=2000&auto=format&fit=crop&q=80",
  // vinyl crate / records
  "https://images.unsplash.com/photo-1483412033650-1015ddeb83d1?w=2000&auto=format&fit=crop&q=80",
  // dj turntable
  "https://images.unsplash.com/photo-1571266028243-d220c6e29ab2?w=2000&auto=format&fit=crop&q=80",
  // acoustic guitar warm
  "https://images.unsplash.com/photo-1510915361894-db8b60106cb1?w=2000&auto=format&fit=crop&q=80",
];

function Backdrop() {
  const [idx, setIdx] = useState(0);

  // Pre-load the next slide so the cross-fade is buttery, not a flash.
  useEffect(() => {
    const nextUrl = HERO_IMAGES[(idx + 1) % HERO_IMAGES.length];
    const img = new Image();
    img.src = nextUrl;
  }, [idx]);

  useEffect(() => {
    const t = setInterval(
      () => setIdx((i) => (i + 1) % HERO_IMAGES.length),
      6000,
    );
    return () => clearInterval(t);
  }, []);

  return (
    <>
      {/* One photo at a time, cross-faded with a slow Ken Burns zoom. */}
      <div aria-hidden className="absolute inset-0 -z-30 overflow-hidden">
        <AnimatePresence mode="sync">
          <motion.div
            key={idx}
            initial={{ opacity: 0, scale: 1.04 }}
            animate={{ opacity: 0.78, scale: 1.0 }}
            exit={{ opacity: 0, scale: 1.0 }}
            transition={{
              opacity: { duration: 1.6, ease: "easeInOut" },
              scale:   { duration: 8.0, ease: "linear" },
            }}
            className="absolute inset-0 bg-cover bg-center"
            style={{
              backgroundImage: `url('${HERO_IMAGES[idx]}')`,
              filter: "saturate(1.05) brightness(0.95) contrast(1.05)",
            }}
          />
        </AnimatePresence>
      </div>

      {/* Soft dark wash — keep text readable but photos remain prominent. */}
      <div
        aria-hidden
        className="absolute inset-0 -z-20"
        style={{
          background:
            "linear-gradient(180deg, rgba(10,10,22,0.18) 0%, rgba(10,10,22,0.42) 55%, rgba(10,10,22,0.95) 100%)",
        }}
      />

      {/* Coloured glow above the photo, beneath the text. */}
      <div
        aria-hidden
        className="absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(60% 50% at 20% 0%, rgba(139,92,246,0.25), transparent 60%)," +
            "radial-gradient(50% 50% at 90% 20%, rgba(6,182,212,0.18), transparent 60%)," +
            "radial-gradient(60% 60% at 50% 110%, rgba(236,72,153,0.20), transparent 60%)",
        }}
      />

      {/* Slide indicator dots */}
      <div
        aria-hidden
        className="absolute bottom-6 right-6 -z-0 flex items-center gap-1.5"
      >
        {HERO_IMAGES.map((_, i) => (
          <span
            key={i}
            className={
              i === idx
                ? "h-1.5 w-6 rounded-full bg-violet transition-all"
                : "h-1.5 w-1.5 rounded-full bg-white/25 transition-all"
            }
          />
        ))}
      </div>
    </>
  );
}

function WaveformShowcase() {
  const { t } = useTranslation();
  const bars = Array.from({ length: 96 }, (_, i) => i);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
        <AudioWaveform className="size-4 text-cyan shrink-0" />
        <span className="mono text-[10px] sm:text-[11px] uppercase tracking-[0.18em] sm:tracking-[0.22em] text-fg-muted min-w-0 truncate">
          {t("landing.showcase_label")}
        </span>
        <span className="ml-auto mono text-[10px] sm:text-[11px] text-fg-muted whitespace-nowrap">
          {t("landing.showcase_meta")}
        </span>
      </div>

      <div className="rounded-xl bg-black/40 border border-white/5 h-24 sm:h-32 flex items-center gap-[2px] px-3 overflow-hidden">
        {bars.map((i) => {
          const phase = (i / bars.length) * Math.PI * 4;
          const h = 18 + Math.abs(Math.sin(phase + i * 0.31)) * 70 + (i % 7) * 1.5;
          return (
            <span
              key={i}
              className="flex-1 rounded-sm"
              style={{
                height: `${h}%`,
                background:
                  i < bars.length / 2
                    ? "linear-gradient(180deg, rgba(139,92,246,0.85), rgba(139,92,246,0.25))"
                    : "linear-gradient(180deg, rgba(6,182,212,0.85), rgba(6,182,212,0.25))",
              }}
            />
          );
        })}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mono text-[11px]">
        <ShowcaseStat label={t("landing.showcase_stat_null")} value="-41.7 dB" tone="cyan" />
        <ShowcaseStat label={t("landing.showcase_stat_recon")} value="0.9995" tone="violet" />
        <ShowcaseStat label={t("landing.showcase_stat_polish")} value="mixback + dynaudnorm" tone="magenta" />
        <ShowcaseStat label={t("landing.showcase_stat_output")} value="WAV · 48 kHz · 24-bit" tone="amber" />
      </div>
    </div>
  );
}

function ShowcaseStat({ label, value, tone }) {
  const map = {
    cyan: "text-cyan",
    violet: "text-violet",
    magenta: "text-magenta",
    amber: "text-amber",
  };
  return (
    <div className="rounded-lg bg-white/[0.025] ring-1 ring-white/5 px-2.5 py-2">
      <div className="text-fg-muted">{label}</div>
      <div className={`text-sm ${map[tone]}`}>{value}</div>
    </div>
  );
}

/* ─── Features ──────────────────────────────────────────────────────────── */

const FEATURES_META = [
  { key: "sep",      icon: <Mic2 className="size-5" />,        accent: "violet" },
  { key: "keytempo", icon: <Music2 className="size-5" />,      accent: "cyan" },
  { key: "stems",    icon: <Layers3 className="size-5" />,     accent: "amber" },
  { key: "score",    icon: <Music3 className="size-5" />,      accent: "magenta" },
  { key: "cue",      icon: <Headphones className="size-5" />,  accent: "cyan" },
  { key: "loop",     icon: <Repeat className="size-5" />,      accent: "magenta" },
  { key: "slow",     icon: <Turtle className="size-5" />,      accent: "violet" },
  { key: "chord",    icon: <Hash className="size-5" />,        accent: "cyan" },
];

function Features() {
  const { t } = useTranslation();
  return (
    <section id="features" className="relative py-16 sm:py-20 md:py-28">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8 sm:space-y-10">
        <SectionHeader
          eyebrow={t("landing.features_eyebrow")}
          title={
            <>
              {t("landing.features_title_a")}
              <span className="gradient-text">{t("landing.features_title_accent")}</span>
              {t("landing.features_title_b")}
            </>
          }
          subtitle={t("landing.features_subtitle")}
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-3.5">
          {FEATURES_META.map((f) => (
            <FeatureCard
              key={f.key}
              icon={f.icon}
              title={t(`landing.feature_${f.key}_title`)}
              desc={t(`landing.feature_${f.key}_desc`)}
              accent={f.accent}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function FeatureCard({ icon, title, desc, accent }) {
  const map = {
    violet: "text-violet bg-violet/15",
    cyan: "text-cyan bg-cyan/15",
    magenta: "text-magenta bg-magenta/15",
    amber: "text-amber bg-amber/15",
  };
  return (
    <motion.div
      whileHover={{ y: -3 }}
      className="hairline rounded-2xl p-5 space-y-3 bg-white/[0.015] hover:bg-white/[0.03] transition-colors"
    >
      <span className={`inline-flex items-center justify-center size-9 rounded-xl ${map[accent]}`}>
        {icon}
      </span>
      <div className="text-sm font-semibold text-fg leading-tight">{title}</div>
      <div className="text-[12.5px] text-fg-muted leading-relaxed">{desc}</div>
    </motion.div>
  );
}

/* ─── Workflow ──────────────────────────────────────────────────────────── */

const STEPS_META = [
  { n: "01", key: "step1", icon: <Link2 className="size-5" />,            accent: "violet"  },
  { n: "02", key: "step2", icon: <SlidersHorizontal className="size-5" />, accent: "cyan"    },
  { n: "03", key: "step3", icon: <Wand2 className="size-5" />,             accent: "magenta" },
  { n: "04", key: "step4", icon: <Headphones className="size-5" />,        accent: "amber"   },
];

const STEP_ACCENT = {
  violet:  { ring: "ring-violet/30",  glow: "from-violet/15  to-transparent", icon: "bg-violet/15 text-violet"   },
  cyan:    { ring: "ring-cyan/30",    glow: "from-cyan/15    to-transparent", icon: "bg-cyan/15 text-cyan"       },
  magenta: { ring: "ring-magenta/30", glow: "from-magenta/15 to-transparent", icon: "bg-magenta/15 text-magenta" },
  amber:   { ring: "ring-amber/30",   glow: "from-amber/15   to-transparent", icon: "bg-amber/15 text-amber"     },
};

function Workflow() {
  const { t } = useTranslation();
  return (
    <section className="py-16 sm:py-20 md:py-28 border-t border-white/5">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 space-y-10 sm:space-y-12">
        <SectionHeader
          eyebrow={t("landing.workflow_eyebrow")}
          title={t("landing.workflow_title")}
          subtitle={t("landing.workflow_subtitle")}
        />

        <div className="relative grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          {/* Subtle connecting line on lg+ */}
          <div
            aria-hidden
            className="hidden lg:block absolute left-0 right-0 top-[3.25rem] h-px bg-gradient-to-r from-transparent via-white/10 to-transparent -z-0"
          />

          {STEPS_META.map((s, i) => {
            const a = STEP_ACCENT[s.accent];
            return (
              <motion.div
                key={s.n}
                initial={{ opacity: 0, y: 8 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-50px" }}
                transition={{ delay: i * 0.06, duration: 0.4 }}
                whileHover={{ y: -3 }}
                className={cn(
                  "relative rounded-2xl p-4 sm:p-5 md:p-6 bg-gradient-to-b ring-1 transition-all",
                  a.glow, a.ring,
                )}
              >
                {/* Big watermark step number */}
                <div className="absolute right-4 top-3 select-none pointer-events-none mono text-4xl sm:text-5xl md:text-6xl font-extrabold text-white/[0.06] leading-none">
                  {s.n}
                </div>

                <div className={cn(
                  "inline-flex items-center justify-center size-10 rounded-xl",
                  a.icon,
                )}>
                  {s.icon}
                </div>

                <div className="mt-3 sm:mt-4 mono text-[10px] uppercase tracking-[0.22em] text-fg-muted">
                  {t("landing.step_label")} {s.n}
                </div>
                <h3 className="mt-1.5 text-base sm:text-lg font-bold text-fg leading-snug break-keep">
                  {t(`landing.${s.key}_title`)}
                </h3>
                <p className="mt-2 text-[12.5px] text-fg-muted leading-relaxed break-keep">
                  {t(`landing.${s.key}_desc`)}
                </p>

                <ul className="mt-3 space-y-1.5 pt-2 border-t border-white/5">
                  {[1, 2].map((bi) => (
                    <li
                      key={bi}
                      className="flex items-start gap-1.5 text-[11.5px] text-fg/85 leading-relaxed break-keep"
                    >
                      <Check className="size-3 mt-0.5 shrink-0 text-fg-muted/70" />
                      <span>{t(`landing.${s.key}_b${bi}`)}</span>
                    </li>
                  ))}
                </ul>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ─── Comparison ────────────────────────────────────────────────────────── */

const DOMAINS_META = [
  { key: "live",     accent: "violet"  },
  { key: "studio",   accent: "cyan"    },
  { key: "practice", accent: "magenta" },
];

function Comparison() {
  const { t } = useTranslation();
  return (
    <section className="py-16 sm:py-20 md:py-28 border-t border-white/5">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8 sm:space-y-10">
        <SectionHeader
          eyebrow={t("landing.compare_eyebrow")}
          title={
            <>
              {t("landing.compare_title_a")}
              <span className="gradient-text">{t("landing.compare_title_accent")}</span>
              {t("landing.compare_title_b")}
            </>
          }
          subtitle={t("landing.compare_subtitle")}
        />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
          {DOMAINS_META.map((d) => (
            <DomainCard
              key={d.key}
              eyebrow={t(`landing.domain_${d.key}_eyebrow`)}
              title={t(`landing.domain_${d.key}_title`)}
              desc={t(`landing.domain_${d.key}_desc`)}
              bullets={[1, 2, 3, 4].map((i) => t(`landing.domain_${d.key}_b${i}`))}
              accent={d.accent}
            />
          ))}
        </div>
        <p className="text-[11px] text-fg-muted/70">
          {t("landing.compare_footer")}
        </p>
      </div>
    </section>
  );
}

function DomainCard({ title, eyebrow, desc, bullets, accent }) {
  const accentMap = {
    violet: "from-violet/15 to-transparent ring-violet/25 text-violet",
    cyan: "from-cyan/15 to-transparent ring-cyan/25 text-cyan",
    magenta: "from-magenta/15 to-transparent ring-magenta/25 text-magenta",
  };
  return (
    <motion.div
      whileHover={{ y: -3 }}
      className={`relative rounded-2xl p-6 bg-gradient-to-b ${accentMap[accent]} ring-1 transition-colors`}
    >
      <div className="mono text-[10px] uppercase tracking-[0.22em] opacity-80 mb-2">
        {eyebrow}
      </div>
      <h3 className="text-xl font-bold text-fg leading-tight">{title}</h3>
      <p className="text-[12.5px] text-fg-muted mt-1.5 leading-relaxed">{desc}</p>
      <ul className="mt-4 space-y-2">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-2 text-[12.5px] text-fg leading-relaxed">
            <Check className="size-3.5 mt-0.5 shrink-0 opacity-90" />
            <span>{b}</span>
          </li>
        ))}
      </ul>
    </motion.div>
  );
}

/* ─── Final CTA ─────────────────────────────────────────────────────────── */

function Cta() {
  const { t } = useTranslation();
  return (
    <section className="py-16 sm:py-20 md:py-28">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 text-center space-y-4 sm:space-y-5">
        <Sparkles className="size-5 text-violet mx-auto" />
        <h2 className="text-2xl sm:text-3xl md:text-4xl font-extrabold tracking-tight">
          <span className="gradient-text">{t("landing.final_cta_title_accent")}</span>
          {t("landing.final_cta_title_tail")}
        </h2>
        <p className="text-fg-muted text-sm sm:text-base">
          {t("landing.final_cta_subtitle")}
        </p>
        <div className="pt-2">
          <Link
            to="/app"
            className="inline-flex items-center gap-2 h-11 sm:h-12 px-6 sm:px-7 rounded-full text-sm font-medium bg-gradient-to-br from-violet to-magenta text-white hover:shadow-[0_18px_56px_-18px_rgba(139,92,246,0.7)] hover:-translate-y-[1px] transition-all"
          >
            {t("landing.final_cta_button")} <ArrowRight className="size-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Helpers ───────────────────────────────────────────────────────────── */

function SectionHeader({ eyebrow, title, subtitle }) {
  return (
    <div className="max-w-2xl space-y-2">
      <div className="mono text-[10px] uppercase tracking-[0.22em] text-fg-muted">
        {eyebrow}
      </div>
      <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">{title}</h2>
      {subtitle && (
        <p className="text-sm text-fg-muted leading-relaxed">{subtitle}</p>
      )}
    </div>
  );
}
