/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg0: "rgb(var(--bg-0) / <alpha-value>)",
        bg1: "rgb(var(--bg-1) / <alpha-value>)",
        bg2: "rgb(var(--bg-2) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        "fg-muted": "rgb(var(--fg-muted) / <alpha-value>)",
        violet: "rgb(var(--accent-violet) / <alpha-value>)",
        cyan: "rgb(var(--accent-cyan) / <alpha-value>)",
        magenta: "rgb(var(--accent-magenta) / <alpha-value>)",
        amber: "rgb(var(--accent-amber) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["Pretendard Variable", "Inter", "ui-sans-serif", "system-ui"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
        "3xl": "1.5rem",
      },
      keyframes: {
        pulseGlow: {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        pulseGlow: "pulseGlow 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
