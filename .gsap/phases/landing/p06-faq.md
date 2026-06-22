# Phase P06 - FAQ

## Scope

- Page: landing
- Section: FAQ
- Recipe Direction: accordion timing polish
- Status: Done — 2026-06-22

## Objective

Make the FAQ section feel intentional, modern, and aligned with the page hierarchy.

## Tasks

- [ ] Inspect the current code and selectors for the FAQ section before editing.
- [ ] Preserve any good existing FAQ motion and remove duplicate or noisy effects first.
- [ ] Align the FAQ motion with the inferred product type: Marketing Site, Dashboard, Booking Platform.
- [ ] Document the motion goal, hierarchy, and fallback behavior for FAQ in the page artifact.
- [ ] Implement the FAQ animation with transform/opacity-first properties.
- [ ] Verify reduced-motion behavior for FAQ.
- [ ] Verify mobile downgrade behavior for FAQ.
- [ ] Update the FAQ status and notes in .gsap artifacts.

## Implementation

- `frontend/src/pages/Landing.tsx` → `FAQSection`. The answer used to mount/unmount
  instantly (`{isOpen && <div>}`) which snapped open/closed. Wrapped it in Framer
  Motion `AnimatePresence` + a `motion.div` that tweens `height: 0 → auto` and
  `opacity` with the page's signature expo-out curve `[0.16,1,0.3,1]` (~0.42s).
- Chose Framer over a GSAP height tween here on purpose: it's a UI-state toggle
  (same family as the existing mobile-menu drawer), height:auto "just works" with
  no scrollHeight measuring/resize bugs, and it keeps one tool for state
  transitions while GSAP stays for the cinematic hero/scroll work.

## Validation

- Reduced Motion: `useReducedMotion()` collapses the tween to 0.15s (quick fade,
  no long height slide). Honors the same contract as AnimatedSection.
- Mobile Downgrade: transform/height + opacity only; no layout thrash, no
  scroll-linked work. Fine on mobile.
- Notes: chevron rotation + card border/shadow were already CSS-transitioned —
  preserved as-is.
