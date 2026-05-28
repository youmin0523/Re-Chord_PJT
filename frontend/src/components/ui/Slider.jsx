import { cn } from "@/lib/utils";

const ACCENT = {
  violet: "from-violet to-magenta",
  cyan: "from-cyan to-violet",
  magenta: "from-magenta to-amber",
  amber: "from-amber to-magenta",
};

export function Slider({ className, accent = "violet", ...rest }) {
  const min = Number(rest.min ?? 0);
  const max = Number(rest.max ?? 100);
  const value = Number(rest.value) || 0;
  const pct = ((value - min) / (max - min)) * 100;

  return (
    <div className="relative w-full">
      <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-white/10 pointer-events-none" />
      <div
        className={cn(
          "absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-gradient-to-r pointer-events-none",
          ACCENT[accent],
        )}
        style={{ left: 0, width: `${pct}%` }}
      />
      <input
        type="range"
        className={cn(
          "relative w-full h-6 appearance-none bg-transparent cursor-pointer",
          "[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5",
          "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white",
          "[&::-webkit-slider-thumb]:shadow-[0_0_0_3px_rgba(139,92,246,0.35),0_6px_18px_-4px_rgba(139,92,246,0.7)]",
          "[&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-110",
          className,
        )}
        {...rest}
      />
    </div>
  );
}
