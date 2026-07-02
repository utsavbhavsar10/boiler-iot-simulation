import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Warm parchment / sepia palette — industrial copper accents
        bg:      "#efe6d3",   // warm cream parchment
        panel:   "#e6d9bd",   // soft sand
        card:    "#f3eada",   // light parchment (cards float up)
        border:  "#cdb994",   // tan border
        ink:     "#3b2c1c",   // espresso text
        muted:   "#8a7355",   // warm taupe
        accent:  "#c2742c",   // copper
        accent2: "#8a4a1f",   // burnt sienna
        good:    "#6b8a3a",   // olive
        warn:    "#d49019",   // mustard amber
        crit:    "#b13a1e",   // rust red
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      boxShadow: {
        warm: "0 6px 24px rgba(80, 50, 20, 0.12)",
        glow: "0 0 24px rgba(194, 116, 44, 0.35)",
      },
      animation: {
        "bounce-dot": "bounceDot 1.2s infinite ease-in-out",
        "fade-in": "fadeIn 0.3s ease-out",
        "pulse-ring": "pulseRing 1.6s infinite",
      },
      keyframes: {
        bounceDot: {
          "0%, 80%, 100%": { transform: "scale(0.6)", opacity: "0.4" },
          "40%": { transform: "scale(1)", opacity: "1" },
        },
        fadeIn: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "none" },
        },
        pulseRing: {
          "0%": { boxShadow: "0 0 0 0 rgba(194,116,44,0.5)" },
          "100%": { boxShadow: "0 0 0 12px rgba(194,116,44,0)" },
        },
      },
    },
  },
  plugins: [],
};
export default config;
