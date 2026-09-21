# Design System — MindfulSpace

> The UI UX Pro Max skill (`ui-ux-pro-max-skill`) is **not available** in this
> environment (only the built-in `customize-opencode` skill exists), so this
> system was designed directly from the brief's hard rules. Where any
> external preset would conflict with the brief (performance budget, ONE
> accent colour, reduced motion), the brief wins.

**Chosen style:** quiet clinical-calm dark tool — "night-time journal", not a
game forge. Surfaces recede; only the portrait of the user's own words (the
AI insight / Maya reply) gets emphasis. No fantasy theming: colour variety
is deliberately *absent* (single accent everywhere) because data-theme tints
belong to character portraits, which this app has none of.

## Palette (ONE accent)

| Token | Value | Use |
|---|---|---|
| `--bg0` | `#0a0f1e` | page base |
| `--bg1` | `#0f172a` | raised base (kept from original) |
| `--surface1` | `#141d33` | cards |
| `--surface2` | `#192440` | hover / selected / inputs |
| `--ink` | `#eef2f9` | primary text |
| `--muted` | `#a9b7cf` | secondary text (≥ 4.5:1 on surfaces) |
| `--faint` | `#7d8aa3` | hints, placeholders |
| `--accent` | `#7dd3fc` | the ONE accent: links, rings, selections, beam, indicator |
| `--accent-ink` | `#082f49` | text on accent fills |
| `--success` | `#34d399` | muted success |
| `--warning` | `#fbbf24` | muted warning |
| `--error` | `#f87171` | muted error |
| `--line` | `rgba(148,163,184,.16)` | 1 px borders |

**Anti-patterns recorded:** gradient text anywhere except the login hero;
multiple accent hues; emoji as UI chrome (replaced with a Lucide-style inline
SVG set, 1.5 px stroke: leaf, clipboard, chat, calendar, send, copy, check,
close, menu); `backdrop-filter` anywhere except the fixed header; stacked
hover effects (now: one subtle background/border change per element);
`transition: all`; animating `background`/`box-shadow`/layout props.

## Type & spacing

- **Font:** Inter (Google Fonts, `display: swap`, `preconnect`), fallback
  `system-ui, "Segoe UI", sans-serif`. Numbers (mood, slots, counters) use
  `font-variant-numeric: tabular-nums`.
- **Scale:** 12 / 13 / 14 / 16 / 20 / 24 / 32 px; line-height 1.6 body.
- **Spacing:** 4 px scale (`--s1:4px … --s8:32px`).
- **Radii:** 10 / 14 / 20 px. **Shadows:** sm / md / lg, all low-alpha black
  (no coloured glows except the single ambient page glow).
- **Cards:** flat `var(--surface1)` + 1 px `var(--line)` + subtle top
  highlight (`::before` 1 px white 6% gradient). No per-card blur.

## Chrome

- `color-scheme: dark`; favicon: inline SVG leaf (data URI).
- Fixed header with `backdrop-filter: blur(12px)` (the single allowed use);
  gains border after ~8 px scroll; hides on scroll-down, returns on
  scroll-up; `scroll-margin-top` under it.
- Sidebar on desktop; slide-in drawer + fading backdrop on ≤ 860 px.
- Focus: `:focus-visible` 2 px accent outline, no movement. All interactive
  elements keyboard-reachable; dialogs trap and restore focus; toasts are
  `aria-live="polite"`; crisis dialog uses `role="alertdialog"`.
- Contrast: body text ~13:1, muted ~7:1, accent-on-dark ~10:1, white on
  `#6b5b95` primary ~4.6:1 — all ≥ 4.5:1. Nothing flashes > 3×/s.
