import type { Config } from "tailwindcss";

/**
 * Tailwind v3 config wired to the shadcn/ui-style CSS variables defined in
 * src/app/globals.css. Deliberately kept on the 3.x line (Phase 1 scaffold
 * standard) — migrating to v4 requires rewriting these token definitions.
 *
 * Owner palette (Prompt 05):
 *   primary   deep navy #102A43  → hsl(209 61% 16%)   (--primary)
 *   accent    teal       #14B8A6  → hsl(173 80% 40%)   (--accent)
 *   background slate-50  #F8FAFC  → hsl(210 40% 98%)   (--background)
 *   surface   white      #FFFFFF  → hsl(0 0% 100%)     (--card / --popover)
 *   warning   amber-500  #F59E0B  → hsl(38 92% 50%)    (--warning)
 *   danger    red-600    #DC2626  → hsl(0 72% 51%)     (--destructive)
 *
 * Supporting neutrals are Tailwind slate steps so borders/muted text stay
 * legible against the slate-50 background. Every color is defined ONLY as a
 * CSS variable in globals.css and referenced here via hsl(var(--…)) — do not
 * rename one side without the other.
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
        // Owner's teal. In shadcn semantics `accent` doubles as a hover
        // background; the button ghost variant therefore hovers on `muted`
        // (see src/components/ui/button.tsx) so raw teal stays reserved for
        // accent-colored UI: badges, links, highlights.
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
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
