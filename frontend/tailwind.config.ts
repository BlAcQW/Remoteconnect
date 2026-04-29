import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0D0F12",
        surface: "#161A1F",
        surface2: "#1F252C",
        border: "#2A2F36",
        accent: "#00E5FF",
        accentDim: "#0096AB",
        muted: "#6B7280",
        success: "#10B981",
        danger: "#EF4444",
      },
      fontFamily: {
        sans: ["var(--font-sora)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 24px rgba(0, 229, 255, 0.15)",
      },
    },
  },
  plugins: [],
};

export default config;
