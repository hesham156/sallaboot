# Phase P03 - Stats

## Scope

- Page: landing
- Section: Stats
- Recipe Direction: count-up on enter
- Status: Done (2026-06-15)

## What Shipped

- `STATS` array extended with `countTo: number | null`, `prefix: string`, `suffix: string`.
- Numeric stats render `<p className="stat-num" data-count-to={...} data-prefix={...}>`. Ratio stat (`٢٤/٧`) renders without these attributes so the count-up loop skips it.
- `ScrollTrigger.create({ trigger: '.stats-section', start: 'top 80%', once: true })` fires the count-up on first viewport entry.
- The count-up uses a proxy object (`{ v: 0 }`) and `onUpdate` rewrites `textContent` via `toArabicDigits(proxy.v)`. No transforms touched → no GPU layer, no compositing cost.
- 80ms stagger between siblings so the four numbers don't all settle at the same instant.

## Reduced Motion

Entire ScrollTrigger creation is inside the `(prefers-reduced-motion: no-preference)` matchMedia branch. The static Arabic value (`+200`, `٪89`, etc.) rendered by React is what reduced-motion users see — no JS mutation needed.

## Files Touched

- `frontend/src/pages/Landing.tsx` — `STATS` array, `toArabicDigits()` helper, JSX data attributes, ScrollTrigger block in `useGSAP`.
