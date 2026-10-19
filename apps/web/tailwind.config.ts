import type { Config } from "tailwindcss";
import defaultTheme from "tailwindcss/defaultTheme";

/**
 * Tailwind v3 config wired to the shadcn/ui-style CSS variables defined in
 * src/app/globals.css — the "examiner's bench" dark world. Deliberately kept
 * on the 3.x line (Phase 1 scaffold standard) — migrating to v4 requires
 * rewriting these token definitions.
 *
 * Layer model:
 *   bench    --background  deep navy ground
 *   panel    --panel       sidebar / toolbar layer (one step off the bench)
 *   plate    --card        content surfaces (machined edge via shadow-plate)
 *   light    --primary     the brand cyan (≈ #28bce2, brand #1CA6C8 family
 *                          brightened for dark grounds) — actions, focus,
 *                          informational state only
 *   judgment --warning / --destructive / --success — amber/red/jade, spent
 *              only where the data is a judgment (badges, meters, alerts)
 *
 * Type voices (loaded once in src/app/layout.tsx via next/font):
 *   --font-sans     Public Sans   — UI, body, labels
 *   --font-display  Source Serif 4 — titles, page headers, charter voice
 *   --font-mono     Spline Sans Mono — IDs, amounts, audit actions, scores
 *
 * Every color is defined ONLY as a CSS variable in globals.css and referenced
 * here via hsl(var(--…)) — do not rename one side without the other.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        panel: "hsl(var(--panel))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        // Brand cyan for accent-colored UI (links, active nav, highlights).
        // Hover backgrounds use `secondary`/`muted`, not the accent itself —
        // the instrument light never smears under the cursor.
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", ...defaultTheme.fontFamily.sans],
        display: ["var(--font-display)", "Georgia", "serif"],
        mono: ["var(--font-mono)", ...defaultTheme.fontFamily.mono],
      },
      boxShadow: {
        // The machined plate: hairline top light, tight contact shadow, long
        // soft fall — offset + blur, never a flat halo.
        plate:
          "inset 0 1px 0 0 hsl(210 40% 90% / 0.05), 0 1px 2px hsl(214 56% 4% / 0.5), 0 16px 40px -20px hsl(214 56% 4% / 0.7)",
        raise:
          "inset 0 1px 0 0 hsl(210 40% 90% / 0.05), 0 2px 6px hsl(214 56% 4% / 0.45), 0 10px 24px -12px hsl(214 56% 4% / 0.6)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      // 12 is the review-queue tint of the design system (badge/nav fills at
      // "cyan/12" per DESIGN.md) but sits outside Tailwind's default opacity
      // scale (0,5,10,15,…), so `/12` modifiers generated no CSS without it.
      opacity: {
        12: "0.12",
      },
      keyframes: {
        scanline: {
          from: { transform: "translateY(4%)", opacity: "0" },
          "12%": { opacity: "1" },
          "88%": { opacity: "1" },
          to: { transform: "translateY(92%)", opacity: "0" },
        },
      },
      animation: {
        scanline: "scanline 5s cubic-bezier(0.45, 0, 0.55, 1) infinite alternate",
      },
    },
  },
  plugins: [],
};

export default config;
