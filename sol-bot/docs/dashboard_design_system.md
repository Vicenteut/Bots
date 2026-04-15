# Sol Dashboard Design System

## Purpose
This guide keeps Sol visually coherent as we iterate. It is intentionally lightweight: a shared set of UI rules for the live dashboard, not a framework or component library.

## Core Palette

- `--bg`: `#0b0b10`
- `--surface1`: `#15151b`
- `--surface2`: `#1d1d25`
- `--surface3`: `#2a2a34`
- `--border`: `#434351`
- `--border2`: `#626272`
- `--text`: `#f4f4f5`
- `--muted`: `#ccccd6`
- `--muted2`: `#9a9aa8`
- `--purple`: `#b026ff`
- `--purple2`: `#d86cff`
- `--purple-dim`: `#6f18a8`
- `--success`: `#22c55e`
- `--danger`: `#ef4444`
- `--warning`: `#a3a3a3`

## Usage Rules

- Sol dark mode should be **high legibility dark**, not cinematic black.
- Purple is the identity color: active states, focus, selected cards, analytics accents, and editorial emphasis.
- Green is reserved for healthy states, publish success, `COMBINADA`, and other positive actions.
- Red is only for real failures or destructive actions.
- Gray handles structure, neutral metrics, and secondary text.
- Warning tones should stay secondary. They are not Sol's main visual identity anymore.

## Typography

- Use `Barlow Condensed` for headers, tabs, labels, and operational section titles.
- Use `IBM Plex Mono` for logs, counters, metadata, badges, timestamps, and machine-like text.

## Spacing Scale

- `--space-1`: `4px`
- `--space-2`: `8px`
- `--space-3`: `12px`
- `--space-4`: `16px`
- `--space-5`: `20px`

Prefer the shared scale over one-off spacing.

## Shape System

- Standard card radius: `14px`
- Larger panel radius: `16px`
- Pill and badge radius: `999px`

## Card Rules

- Cards should feel editorial and operational, not glossy.
- Use subtle gradients or tonal lifts instead of flat black rectangles.
- Borders should be visible at rest, not only on hover.
- Hover states should be deliberate: small lift, clearer border, or soft glow.
- Left accent borders are acceptable for semantically important cards.

## Button Rules

- Primary actions: purple.
- Positive generation/publish actions: green.
- Destructive actions: red outline or red tint.
- Utility buttons in the status bar should remain secondary and never overpower live metrics.

## Desktop Rules

- The status bar must remain readable and stable.
- Critical telemetry should stay visible before utility controls.
- Deep panels must own their own scroll.
- Tables should use sticky headers and readable hover states.

## Mobile Rules

- Minimum tap target: `44px`.
- Prefer one-column reading flows.
- Do not rely on drag as the only interaction.
- Keep confirmation actions spacious and clear.
- Respect `prefers-reduced-motion`.

## Anti-Patterns

- Do not introduce extra accent colors unless there is a strong semantic reason.
- Do not shift Sol toward light mode or pastel palettes.
- Do not overuse glow or glassmorphism.
- Do not let warning colors become the dominant visual language again.
