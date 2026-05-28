import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileAudio, AlertTriangle } from "lucide-react";
import { getFormats } from "@/lib/api";
import { cn } from "@/lib/utils";

export function FormatPicker({ format, sampleRate, bitDepth, sourceSr, onChange }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);

  useEffect(() => {
    getFormats().then((m) => setRows(m.output_formats)).catch(() => {});
  }, []);

  const current = rows.find((r) => r.name === format);
  const supportsSr = current?.sample_rates ?? [44100, 48000];
  const supportsBits = current?.bit_depths ?? ["24"];
  const lossy = format === "mp3" || format === "aac";
  const upsampled = sourceSr ? sampleRate > sourceSr : false;

  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <FileAudio className="size-4 text-amber" />
        <span className="text-sm font-semibold">Export</span>
      </div>

      <div>
        <div className="text-[11px] text-fg-muted mb-1.5">{t("format.format")}</div>
        <div className="grid grid-cols-5 gap-2">
          {["wav", "flac", "aiff", "mp3", "aac"].map((f) => (
            <button
              key={f}
              onClick={() => {
                const row = rows.find((r) => r.name === f);
                const nextSr = row?.sample_rates.includes(sampleRate)
                  ? sampleRate
                  : (row?.sample_rates[1] ?? 48000);
                const nextBits = row?.bit_depths.includes(bitDepth)
                  ? bitDepth
                  : (row?.bit_depths.includes("24") ? "24" : (row?.bit_depths[0] ?? "24"));
                onChange({ format: f, sampleRate: nextSr, bitDepth: nextBits });
              }}
              className={cn(
                "rounded-lg py-2 text-xs uppercase tracking-wider transition-all",
                format === f
                  ? "bg-gradient-to-br from-violet/30 to-magenta/30 text-fg ring-1 ring-violet/40"
                  : "bg-white/5 text-fg-muted hover:text-fg",
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="text-[11px] text-fg-muted mb-1.5">{t("format.sample_rate")}</div>
        <div className="grid grid-cols-4 gap-2">
          {supportsSr.map((sr) => {
            const isUp = sourceSr ? sr > sourceSr : false;
            return (
              <button
                key={sr}
                onClick={() => onChange({ format, sampleRate: sr, bitDepth })}
                className={cn(
                  "rounded-lg py-2 px-1 text-xs mono transition-all",
                  sr === sampleRate
                    ? "bg-cyan/15 text-cyan ring-1 ring-cyan/40"
                    : "bg-white/5 text-fg-muted hover:text-fg",
                )}
              >
                {sr / 1000} kHz
                {isUp && <span className="ml-1 text-amber">↑</span>}
              </button>
            );
          })}
        </div>
      </div>

      {!lossy && (
        <div>
          <div className="text-[11px] text-fg-muted mb-1.5">{t("format.bit_depth")}</div>
          <div className="grid grid-cols-3 gap-2">
            {["16", "24", "32f"]
              .filter((b) => supportsBits.includes(b))
              .map((b) => (
                <button
                  key={b}
                  onClick={() => onChange({ format, sampleRate, bitDepth: b })}
                  className={cn(
                    "rounded-lg py-2 text-xs mono transition-all",
                    b === bitDepth
                      ? "bg-magenta/15 text-magenta ring-1 ring-magenta/40"
                      : "bg-white/5 text-fg-muted hover:text-fg",
                  )}
                >
                  {b}-bit
                </button>
              ))}
          </div>
        </div>
      )}

      {upsampled && (
        <div className="flex items-start gap-2 text-[11px] text-amber/90 bg-amber/10 rounded-md px-2.5 py-2">
          <AlertTriangle className="size-3.5 shrink-0 mt-0.5" />
          <span>
            {t("format.upsample_note1")} {t("format.upsample_note2")}
          </span>
        </div>
      )}
    </div>
  );
}
