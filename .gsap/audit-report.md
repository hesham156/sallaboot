# Animation Audit Report - sallaboot

## Workflow State

- Last Audit Mode: gsap-refactor
- Resume Rule: read this file before repeating an audit

## Summary

- Date:
- Scope:
- Overall Health:

## Must Fix

- [x] Hero entrance: Framer Motion `staggerVariants` provided no cinematic hierarchy — all 5 copy elements animated identically at the same pace. Fixed with a deliberate GSAP timeline.
- [x] Floating cards: Framer Motion `animate: { y: [0, -10, 0] }` infinite caused both cards to oscillate in sync. Fixed with different delays (0.8s vs 2.0s) via GSAP.

## Should Fix

- [ ] Stats section: no count-up animation — numbers appear statically. P03 target.
- [x] FAQ accordion: no open/close animation — content snapped in/out instantly. Fixed (P06, 2026-06-22) with a Framer `AnimatePresence` height/opacity tween, reduced-motion aware.
- [ ] Feature cards: Framer Motion `whileHover={{ y: -6 }}` and stagger reveal still in place — refactor to GSAP ScrollTrigger in P02.

## Nice To Have

- [ ] How It Works: step connector line could draw in as each step reveals (P05).
- [ ] CTA: teal gradient could shimmer on scroll-enter (P10).

## Fixes Applied

### Round 1 — drifted off main, reverted by git checkout

The earlier P01/P11/Lenis work was lost when the working tree was reset
during the post-pull cleanup. Treat these as reference history, not as
current code state.

### Round 2 — 2026-06-15 (current code on disk)

- **P00 Smooth scroll** — `frontend/src/hooks/useLenis.ts`. Lenis instance synced to `gsap.ticker`, `ScrollTrigger.update` on every Lenis frame. Skipped under `prefers-reduced-motion`. Mounted in `Landing.tsx` via `useLenis()`.
- **P01 Navbar polish** — `ScrollTrigger.create` toggles a `.is-scrolled` class on `.site-nav` once the user scrolls past `top -60`. Class transitions `background-color`, `box-shadow`, and `border-color` over 250ms via inline `<style>` block. Reverts on scroll-up via `onLeaveBack`.
- **P11 Hero cinematic entrance** — Single `gsap.timeline` runs once on mount. Sequence: badge → headline → desc → CTAs (stagger 80ms) → social proof → mockup scale-in. `power3.out` for entrances, `power2.out` on the mockup with slightly longer 0.9s duration. Initial state pinned with `gsap.set({ autoAlpha: 0, y: 24 })` so there's no FOUC before the timeline runs.
- **P11 Floating cards** — GSAP `yoyo: true, repeat: -1` with different durations (2.4s vs 2.8s) and delays (1.2s vs 1.9s) so the two badges drift independently. Replaces the Framer `animate: { y: [0,-10,0] }` infinite loop that synced both in lock-step.
- **P11 Mockup parallax** — `ScrollTrigger` with `scrub: true` drifts the mockup down `yPercent: 12` as the hero leaves. Replaces Framer's `useScroll`/`useTransform` so the trigger pauses when off-screen instead of running every scroll event.
- **P03 Stats count-up** — `ScrollTrigger.create({ start: 'top 80%', once: true })` proxies an object's `v` from 0 to the target (`+200`, `٪89`, `٪40`). `٢٤/٧` skipped because it's a ratio. `toArabicDigits()` rewrites `textContent` in Arabic-Indic digits so the rendered text matches the static design.
- **Reduced motion** — Entire animation block wrapped in `gsap.matchMedia`. The `(prefers-reduced-motion: reduce)` branch resets everything to `autoAlpha: 1, y: 0, scale: 1` so nothing stays hidden; counts skip and show their static Arabic value.

## Refactor Snapshot - landing

- Existing Motion Stack: Framer Motion
- Matched Files: api.ts, App.tsx, ErrorBoundary.tsx, useSEO.ts, main.tsx, BlogPost.tsx, ErrorPage.tsx, Landing.tsx
- Planned Phases: P01 Navigation, P02 Feature Grid, P03 Stats, P04 Testimonials, P05 Timeline, P06 FAQ, P07 Pricing, P08 Logos, P09 Form, P10 CTA, P11 Hero, P12 Showcase
- Findings:
  - GSAP does not appear to be implemented yet on the matched files.
  - Hero and repeated-card motion should not carry equal visual weight.
- Recommended Improvements:
  - Use a staged hero reveal with headline, supporting copy, and CTA arriving in deliberate sequence.
  - Use one card system for the grid and keep the stagger controlled so the section feels premium, not noisy.
  - Use count-up animation only when the stats enter view and only once.
  - Consider a subtle navbar polish on scroll rather than a dramatic transformation.
  - Use restrained pricing-card emphasis so the CTA hierarchy stays clear without making the section feel gimmicky.
  - Keep logo motion understated and credibility-focused rather than attention-seeking.
  - Use state-based form polish like focus, validation, and success transitions instead of theatrical entrance effects.
  - Reserve marquee, parallax, or layered depth for a showcase section instead of distributing spectacle everywhere.
  - Animate charts and dashboards for clarity first, spectacle second.
  - Use fast, low-friction transitions for search and filter changes so the UI stays responsive.
- Open Questions:
  - Should the workflow install GSAP now, or only prepare the spec and phased plan?
  - Should charts and metrics animate softly for readability, or should they feel more dramatic and presentational?
  - Should the hero motion feel premium and cinematic, or quiet and product-focused?
  - Do you want smooth scrolling like Lenis, or should native scrolling stay untouched?
  - Should forms use only subtle focus polish, or do you want stronger field and success-state motion?
  - Should partner or client logos stay subtle, or should they get motion emphasis as social proof?
- Constraints:
  - Data-heavy screens need clarity-first motion and low distraction.
  - Forms and auth flows need utility-first motion, not theatrical timing.
