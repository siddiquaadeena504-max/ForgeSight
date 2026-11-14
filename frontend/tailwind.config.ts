import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#111214", panel: "#191b1e", raised: "#212428", line: "#2c2f34", lineStrong: "#3a3e45",
        ink: "#f0efec", ink2: "#c3c2b7", muted: "#8d9096",
        accent: "#3987e5", accentDim: "#1c5cab",
        good: "#0ca30c", warn: "#fab219", serious: "#ec835a", crit: "#d03b3b",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
