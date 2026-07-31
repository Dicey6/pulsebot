import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        pulse: {
          purple: "#7C3AED",
          "purple-light": "#A78BFA",
          green: "#4ADE80",
          red: "#F87171",
          dark: "#0B0B14",
          card: "#12121F",
          border: "#1E1E35",
        },
      },
    },
  },
  plugins: [],
};
export default config;
