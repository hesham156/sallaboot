# Phase P11 - Hero

## Scope

- Page: landing
- Section: Hero
- Recipe Direction: hero-text-reveal + layered media parallax
- Status: Done (2026-06-15)

## What Shipped

- GSAP timeline scoped via `useGSAP({ scope: pageRef })`.
- Initial state pinned with `gsap.set('.hero-anim', { autoAlpha: 0, y: 24 })` and `gsap.set('.hero-mockup', { autoAlpha: 0, scale: 0.94, y: 16 })` to prevent FOUC.
- Sequence: `.hero-badge` → `.hero-headline` (-0.3) → `.hero-desc` (-0.45) → `.hero-cta` (-0.4, stagger 80ms) → `.hero-social` (-0.4) → `.hero-mockup` (-0.7, 0.9s). Negative offsets create overlapping reveal — feels orchestrated, not robotic.
- Floating badges: independent `yoyo: true, repeat: -1` tweens with different durations + delays so the two cards never lock to the same phase.
- Scroll parallax: `ScrollTrigger({ scrub: true })` drifts the mockup `yPercent: 12` between `top top` and `bottom top`. Browser-native scroll math via ST — no Framer dual-handler conflict.

## Reduced Motion

`gsap.matchMedia('(prefers-reduced-motion: reduce)')` branch resets every animated element to its resting state (`autoAlpha: 1, y: 0, scale: 1`) so nothing is invisible.

## Files Touched

- `frontend/src/pages/Landing.tsx` — Hero JSX + GSAP timeline + initial-state set
- `frontend/src/hooks/useLenis.ts` — Lenis ticker integration (required for ScrollTrigger smoothness)
