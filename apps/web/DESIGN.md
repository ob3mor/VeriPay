---
name: VeriPay
description: AI-assisted invoice & payment fraud detection — decision support with a human verdict
colors:
  bench: "#091320"
  panel: "#0D1826"
  plate: "#121D2B"
  raised-tint: "#1D2A39"
  hairline: "#243242"
  input-well: "#314153"
  ink: "#F5F7FA"
  ink-muted: "#A1ACBA"
  instrument-cyan: "#28BCE2"
  instrument-cyan-bright: "#53CBEA"
  judgment-amber: "#FBBF24"
  judgment-red: "#F87272"
  judgment-jade: "#35D49A"
typography:
  display:
    fontFamily: "'Source Serif 4', Georgia, serif"
    fontSize: "1.75rem–2.75rem"
    fontWeight: 600
    lineHeight: 1.14
    letterSpacing: "-0.01em"
  body:
    fontFamily: "'Public Sans', system-ui, sans-serif"
    fontSize: "0.875rem–1.125rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "'Spline Sans Mono', monospace"
    fontSize: "0.6875rem–0.75rem"
    fontWeight: 500
    letterSpacing: "0.08em"
rounded:
  sm: "2px"
  md: "4px"
  lg: "6px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32–40px"
components:
  button-primary:
    backgroundColor: "{colors.instrument-cyan}"
    textColor: "{colors.bench}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "40px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "40px"
  input:
    backgroundColor: "{colors.bench}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "40px"
  card-plate:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Design System: VeriPay — "The Examiner's Bench"

## Overview

**Creative North Star: "The Examiner's Bench"**

VeriPay's interface is a dark examination bench in a finance ops room: deep navy grounds layered like stacked dossier paper, separated by hairlines, lit by one precise cyan instrument — the color of the machine having looked at something. Everything amber, red or jade is a judgment color: it appears only where the data is a judgment (severity, outcomes, verification states), never as decoration. Titles are set in an engraved serif (the charter voice), UI copy in a civic sans, and every measurement — invoice numbers, amounts, audit actions, scores — in a soft mono. The machine never renders a verdict; the interface never renders one either.

Density is instrument-grade: tables, evidence panels and chips carry real data at comfortable contrast (body text ≥ 4.5:1 everywhere). Personality lives in precision — machined card edges, squarish spec-label chips, a single scan-line motion moment — not in ornament.

**Key Characteristics:**
- Three-layer navy ground: bench → panel → plate, separated by hairlines
- One cyan for actions, focus and informational state — and nothing else
- Serif titles, sans UI, mono measurement
- Chips are squarish spec-labels with a leading dot
- One authored motion moment (the scan line); everything else is 150ms state feedback

## Colors

The palette is a dark navy ground with one cyan accent and three judgment hues. Source of truth: the HSL channel variables in `src/app/globals.css`, consumed by `tailwind.config.ts` via `hsl(var(--…))`; the hex values here are their resolved equivalents.

### Primary
- **Instrument Cyan** (#28BCE2, `--primary`/`--ring`): primary buttons (solid, with navy ink text), focus rings, active navigation, informational badges, links. Brand family of the owner's #1CA6C8 logo cyan, brightened for dark grounds. Bright enough for 4.5:1+ text on every tint it sits on.
- **Instrument Cyan Bright** (#53CBEA, `--accent`): link text and hover states one step brighter than the fill.

### Secondary
- **Judgment Amber** (#FBBF24, `--warning`): medium severity, review-required states, rate-limit alerts.
- **Judgment Red** (#F87272, `--destructive`): high severity, failures, destructive actions; solid critical chips use it as fill with navy ink text.
- **Judgment Jade** (#35D49A, `--success`): verified/approved-by-human states and "no material discrepancies".

### Neutral
- **Bench** (#091320, `--background`): the page ground.
- **Panel** (#0D1826, `--panel`): sidebars, toolbars, table header bands — the second ground layer.
- **Plate** (#121D2B, `--card`/`--popover`): content cards and dialogs.
- **Raised Tint** (#1D2A39, `--secondary`/`--muted`): icon plates, meter tracks, quiet chips, skeleton shimmer.
- **Hairline** (#243242, `--border`): all rules and card borders (often at /60–/70 alpha for rhythm).
- **Input Well** (#314153, `--input`): input borders; wells are recessed with an inset shadow.
- **Ink** (#F5F7FA, `--foreground`) and **Ink Muted** (#A1ACBA, `--muted-foreground`): text and secondary text.

### Named Rules
**The Instrument Light Rule.** Cyan marks where the machine acts or reports — actions, focus, "you are here", informational state. It never decorates: no cyan banners, no cyan for judgment, hover backgrounds use the raised tint, never the accent.
**The Judgment Colors Rule.** Amber/red/jade are spent only by the data (severity, outcomes, verification). A screen with no judgment in it shows no judgment colors.
**The Navy Ink Rule.** Every solid color fill (cyan, amber, red, jade) carries navy ink text, never white — this is what keeps solid fills at 4.5:1+ on a dark theme.

## Typography

**Display Font:** Source Serif 4 (Georgia fallback) — via next/font, self-hosted at build
**Body Font:** Public Sans (system-ui fallback)
**Label/Mono Font:** Spline Sans Mono

**Character:** an engraved certificate voice (serif) over a civic, audit-grade sans, with mono reserved for anything that is a measurement. Three voices, never more.

### Hierarchy
- **Display** (600, 1.75–2.75rem, 1.14): page titles, landing hero, empty-state titles, dialog titles. Never UI labels or buttons.
- **Title** (600–700 sans, 1rem–1.25rem): card titles, section heads inside plates.
- **Body** (400 sans, 0.875rem, 1.6): copy, descriptions; max-w-2xl for prose.
- **Label** (500 mono, 0.6875rem, 0.08em, uppercase): table headers, fine print; plain mono (no case change) for IDs, amounts, audit actions, request IDs.
- **Stat numerals** (600 serif, tabular): the large overview figures — the financial-report moment.

### Named Rules
**The Measurement Voice Rule.** Anything the API returns as an identifier or quantity (case numbers, masked accounts, scores, actions like `document.uploaded`) is set in Spline Sans Mono. Prose never goes mono.

## Layout

Single-column dashboard under a 240px fixed sidebar (panel layer) and a hairline topbar; content flows full-width with 32–40px gutters and a consistent `space-y-6/8` rhythm — each page is PageHeader (title + description + hairline) then content. Landing is a max-w-6xl two-column hero (copy left, dossier plate right), a full-width charter plate, then three hairline-divided principle columns. Mobile: sidebar collapses to a horizontally scrollable pill nav; grids collapse to single column. Spacing rhythm is Tailwind's 4px scale; more space above a heading than below it.

## Elevation & Depth

Depth is layering first, shadow second: the three ground layers (bench/panel/plate) separate surfaces before any shadow is applied. Shadows exist in two roles, both with real offset and blur.

### Shadow Vocabulary
- **plate** (`inset 0 1px 0 0 hsl(210 40% 90% / 0.05), 0 1px 2px hsl(214 56% 4% / 0.5), 0 16px 40px -20px hsl(214 56% 4% / 0.7)`): every card and dialog — a machined top edge plus a long soft fall.
- **raise** (same inset, tighter 0 2px 6px + 0 10px 24px -12px): small lifted elements (the empty-state motif's document glyph).
- **well** (`inset 0 1px 2px hsl(214 56% 4% / 0.4)`): inputs and selects — recessed, not raised.

### Named Rules
**The Machined Edge Rule.** Every plate carries the inset top highlight. It is what separates "built" from "assembled" on a dark theme.

## Shapes

Crisp instrument geometry: 6px radius on cards, 4px on controls, 2px on chips. Hairline borders (1px, `--border`) are the universal separator — full-width rules, never colored side-stripes. Chips are squarish spec-labels (rounded-sm) with a leading 6px dot, not pills. The signature silhouette is the empty-state motif: a dashed scan frame with a cyan light-edge at its foot, framing a small document glyph.

## Components

### Buttons
- **Shape:** 4px radius, 40px height (36px small), 150ms state transitions.
- **Primary:** solid instrument cyan with navy ink text and a tight contact shadow; hover deepens to /90, active /80.
- **Outline:** transparent on a hairline; hover tints the border cyan/40 and raises the fill to the secondary tint.
- **Ghost / Secondary / Link:** ghost hovers on the raised tint (never the accent); link is cyan with underline-on-hover.
- **Focus:** 2px cyan ring with a 2px bench-colored offset, everywhere.

### Status & Severity Chips
- **Style:** 2px radius, 12%-15% tint of the tone as fill, bright tone text, 30–40% tone border, 6px leading dot (StatusBadge).
- **Severity ladder:** low = neutral slate, medium = amber, high = red, critical = solid red with navy ink (the strongest treatment). One ladder across the whole product.

### Cards / Containers
- **Corner Style:** 6px radius.
- **Background:** plate; header/footer bands may sit on the panel layer at 60%.
- **Shadow Strategy:** shadow-plate (see Elevation).
- **Border:** 1px hairline, /70 for rhythm.
- **Internal Padding:** 24px.

### Inputs / Fields
- **Style:** recessed well (bench at 60% over the plate, inset well shadow), 1px input-well border, 4px radius.
- **Focus:** border shifts cyan/50 + 2px cyan ring/60 with a 1px transparent offset.
- **Disabled / Error:** 50% opacity; errors render through ErrorState/FormAlert plates in judgment red with the API's own message.

### Navigation
- Sidebar (panel layer): mark + wordmark top, items with cyan active state (cyan/12 fill + cyan text + 6px dot), hover on raised tint; charter fine print (R1/R2 in cyan mono) at the foot. Topbar: hairline, sticky with backdrop blur. Mobile: horizontal pill nav on panel.

### The Dossier Plate (signature)
The landing's product mock and the empty-state motif share one device: a plate presented as an evidence document — mono header band, honest chips, and (on the landing only) a slow cyan scan-line sweeping it once every 5s (static under prefers-reduced-motion). It is the only orchestrated motion in the system.

## Do's and Don'ts

### Do:
- **Do** keep the three-layer ground: new surfaces pick bench, panel or plate and separate with hairlines.
- **Do** set every identifier, amount and audit action in mono with tabular numerals in tables.
- **Do** use the severity ladder exactly as defined — gradation is information.
- **Do** pair every solid fill with navy ink text.
- **Do** give interactive elements all five states (hover, focus-visible, active, disabled, loading) — the system's baseline.

### Don't:
- **Don't** use cyan decoratively — it is the machine's light, spent by actions, focus and informational state only.
- **Don't** render approval or genuineness vocabulary anywhere; the strongest allowed label is "No material discrepancies" (PRODUCT.md R1/R2 constrains the UI).
- **Don't** put white text on solid color fills, or add kickers/eyebrows above headings — headings carry their own weight.
- **Don't** use glow, glass, or tiled grid backgrounds; the bench is lit by one radial light on Persuade surfaces and plain elsewhere.
- **Don't** orchestrate page-load motion; Operate surfaces load into the task. The scan line is the single authored moment.
