# Motion System — MindfulSpace

> Restrained motion for a mental-wellness tool. Calm first: one thing moves at a
> time, everything has a purpose, every state change animates in *and* out.
> Adapted from the DreamForge motion brief to this repo (Flask + vanilla
> HTML/CSS/JS, single `templates/index.html`). Backend routes and logic are
> untouched.

**Animation library (only):** Motion (vanilla JS), pinned exactly —
`motion@13.4.0` (latest stable per npm registry, 16 Sep 2026), imported as a
module:

```js
import { animate, stagger, inView, scroll, press }
  from "https://cdn.jsdelivr.net/npm/motion@13.4.0/+esm";
```

No React, no build step, no GSAP, no Motion+ (paid) features. If the CDN
import fails the UI still works — all Motion calls sit behind a `motionOK`
flag and CSS covers hover/focus/fades. Text splitting is done by hand
(`[data-split]` → word `<span>`s + `stagger()`).

**CSS-first rule:** hover/focus colour changes, simple fades, `@starting-style`,
and `grid-template-rows: 0fr → 1fr` accordions are pure CSS. Motion is used
for springs, stagger, interruptible sequences, `hover()`/`press()` gestures,
`inView`/`scroll` effects, and `document.startViewTransition` shared-element
fallbacks (the `animateView` API did not exist in the pinned vanilla bundle,
so View Transitions are called natively with a 200 ms crossfade fallback).

## Tokens

| Token | Value |
|---|---|
| `fast` | 140 ms (exits, micro-feedback) |
| `base` | 240 ms (entrances, default) |
| `slow` | 420 ms (hero sequence, dialog enter) |
| `ease-out` | `cubic-bezier(.16,1,.3,1)` |
| exits | ~60–70% of entrance length |
| shifts | 8 / 12 / 16 px only |
| `snappy` spring | `{ stiffness: 400, damping: 32 }` (press, indicator) |
| `soft` spring | `{ stiffness: 180, damping: 22 }` (glow follow, tilt) |
| stagger | max 6 items, 40–70 ms apart, whole sequence < 600 ms, nothing waits > 200 ms |
| animatable props | `transform`, `opacity`, short-lived `filter: blur(≤12px)` only. Bars use `scaleX`. Never `width/height/top/left/background/box-shadow` on large or frequent elements. No `transition: all`. |
| hover | one subtle effect per element, clickable things only |
| focus | colour/ring only, no movement (`:focus-visible` 2 px accent ring) |
| `will-change` | at most 3 elements at once, removed on animation finish |
| hidden pattern | `[hidden]` + `.is-open` state classes so elements animate *out*; never bare `display:none` toggles in JS |

**Reduced motion** (`matchMedia('(prefers-reduced-motion: reduce)')` + CSS
`@media (prefers-reduced-motion: reduce)`): no transforms, no loops, no
pointer effects; opacity fades ≤ 150 ms only; glow is static; skeletons are
static; typing indicator is static text.

**Ambient discipline:** at most one looping animation on screen at a time
(typing dots *or* border beam *or* skeleton shimmer). All pause when the tab
is hidden (`visibilitychange`) or the element is off-screen
(`IntersectionObserver`).

## Baseline audit (before)

Static audit of `templates/index.html` (~495 lines, no external requests):

- None of the DreamForge anti-patterns existed here: no pulsing blobs, no
  conic-gradient layers, no particles, no animated background gradient, no
  `textGlow`, no `transition: all`, no `backdrop-filter`.
- Real problems found: state changes popped with no animation
  (`slotsCard`/`bookingCard`/`typingIndicator` via bare
  `style.display = block/none` — nothing could animate out); blocking
  `alert()`/`confirm()` for distress intervention, summaries, booking confirm,
  cancel; full `location.reload()` after every action; chat messages appended
  with no enter animation; slot loading was plain text (no skeleton, layout
  shift when results arrived); no `prefers-reduced-motion`; no visible focus
  styles; sidebar vanished (`display:none`) on mobile with no drawer; emoji
  used as UI chrome; numbers not in `tabular-nums`.
- Page weight was already light (no Performance-trace long tasks attributable
  to animation), so the win here is perceived smoothness, CLS, and
  accessibility — not removing heavy layers. Chrome DevTools Performance
  traces / Lighthouse / Playwright could not run in this sandbox (no browser),
  so before/after numbers below are structural, verified by code inspection
  and Flask boot tests instead of traces.

## Effect table

| # | Effect | Trigger | Duration / easing | Reduced-motion behaviour | Reference | What we adapted |
|---|---|---|---|---|---|---|
| 1 | Ambient background: static dot pattern + one radial glow on a spring | pointermove, fine-pointer only | soft spring; CSS 240 ms fallback | static glow, no movement | Aceternity Spotlight look; Motion `js-spring-follow-cursor` | rewrote as one 480 px glow + CSS dot grid; no canvas/particles |
| 2 | Hero title + CTA words rise + fade | first paint, once | 12 px rise, 60 ms stagger, total < 500 ms, ease-out | instant opacity fade ≤ 150 ms | React Bits BlurText/SplitText look; Motion `js-stagger` | hand-split words, gradient text on hero title only |
| 3 | Scroll reveals + supporter-grid distance stagger | `inView`, once | base 240 ms ease-out; 40–70 ms apart, ≤ 6 items, capped 200 ms delay | fade ≤ 150 ms, no shift | Magic UI Blur Fade look; `js-scroll-triggered`, `js-staggered-grid` | distance-from-first-card ordering instead of index ordering |
| 4 | Primary buttons: press spring, hover, idle→loading→success/error | click / `press()` / `hover()` | press snappy spring; state fades fast 140 ms; shimmer sweep only while loading; fixed min-width so labels don't jump | no scale, colour + text change only | Magic UI Shimmer Button look; `js-press`, `js-hover`, `js-multi-state-badge` | no lift, no permanent shimmer |
| 5 | Journal character counter | textarea input, nears limit (800) | number pop snappy spring; colour fast 140 ms | colour + text only | Motion `js-characters-remaining` | spring pop + warn/error colours |
| 6 | Booking stepper + progress bar + border beam + skeletons | supporter/date/slot/select state; slot fetch | bar `scaleX` base 240 ms; beam 1.6 s loop only while loading; skeleton shimmer transform-only | bar jumps without animation; no beam; static skeletons | Motion `js-loading-progress-bar`; Magic UI Border Beam / Aceternity moving border | beam removed on completion; skeletons reserve layout (no CLS) |
| 7 | SIGNATURE reveal: insight card blur-to-sharp + mood CountUp | server-rendered insight on load; chat AI message on stream end | blur ≤ 12 px → sharp < 300 ms; numbers `tabular-nums` count-up ~500 ms; whole reveal < ~800 ms; space reserved | fade ≤ 150 ms, final values set instantly | Magic UI Number Ticker / React Bits CountUp look; `js-html-content` approach | **ember/confetti burst SKIPPED** — wrong emotional register for a distress-support tool; quiet reveal only |
| 8 | Supporter-card tilt + glare | pointer, fine-pointer only | soft spring, max ±6°; glare via `--gx/--gy` vars | disabled entirely | React Bits tilt / Aceternity 3D card look; `js-tilt-card`, `js-conic-gradient-pointer` idea | form cards never tilt; transform set with `will-change` removed after |
| 9 | Tone tabs sliding indicator + arrow-key nav | click / ArrowLeft/Right/Home/End | indicator snappy spring; panel fade 140 ms + 8 px | indicator jumps, no slide | `react-smooth-tabs` behaviour ported | measured `offsetLeft/Width`, `role=tablist` |
| 10 | Accordions (Last check-in / Summary / Sessions) | click, `aria-expanded` | CSS `grid-template-rows 0fr→1fr` base 240 ms both directions | instant toggle | Motion `js-accordion` behaviour | pure CSS (no `animateLayout`/Motion+); animates open *and* close |
| 11 | Chat: 8 px rise-in, 3-dot typing, smooth scroll, inline retry | message append / stream / failure | enter 180 ms ease-out; dots 1.2 s pulse (sole loop); `scrollTo smooth` | no rise; static "typing…"; `auto` scroll | Motion `js-loading-three-dots-pulse` | failed send keeps frame + retry button, never blank |
| 12 | Native `<dialog>` modals (confirm / notice / crisis) | clear/end/cancel/booking/distress | backdrop fade base; dialog scale .96→1 slow 420 ms enter, fast 140 ms exit | fade ≤ 150 ms, no scale | Motion `js-modal`, `js-family-dialog` (+ `animateView` idea) | `showModal`, focus restore, Esc closes; replaces all `alert`/`confirm` |
| 13 | Supporter → booking shared-element | slot select | `document.startViewTransition` when available, else 200 ms crossfade | instant swap | `js-shared-view-animation` / `js-app-store` / `js-lightbox` ideas | scoped `animateView`-equivalent via native API; no FLIP library |
| 14 | Toasts + list FLIP | booking/cancel/chat/clear actions | enter 180 ms rise 8 px; list FLIP base 240 ms; `aria-live="polite"` | instant add/remove | Magic UI Animated List look; `js-notifications-list/stack` | replaces `alert()`; at most one loop; toasts never block clicks |
| 15 | Header border on scroll + hide-on-down + mobile drawer | `scroll()` / scroll listener | border fade fast; header translate base; drawer slow in / fast out + backdrop fade | no hide-on-scroll; drawer fades only | `react-scroll-hide-header` ported | `scroll-margin-top` under fixed header; focus moved into drawer |
| 16 | Slot refresh crossfade, copy-summary check pop, error states | re-fetch / copy / validation & fetch failure | crossfade 200 ms (never blank); check pop snappy, revert ~1.5 s; error border fast + message fade | colour/text only, no pop | — | **no shake on error** (vestibular + tone); border + message + toast |

NOT built (with reason): parallax, marquees/tickers, custom cursor,
meteors/aurora/particles/sparkles, smooth-scroll hijacking,
typewriter/scramble text, page wipes, more than one concurrent loop —
all excluded per brief §"NOT wanted" and inappropriate for a calm
wellness surface.
