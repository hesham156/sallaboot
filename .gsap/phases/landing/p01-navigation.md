# Phase P01 - Navigation

## Scope

- Page: landing
- Section: Navigation
- Recipe Direction: navbar polish on scroll
- Status: Done (2026-06-15)

## What Shipped

- Inline `<style>` block adds `.site-nav.is-scrolled` rules (deeper bg, soft shadow, transparent bottom border).
- `ScrollTrigger.create({ trigger: '.hero-section', start: 'top -60', onEnter, onLeaveBack })` toggles the class.
- 250ms CSS transition on `background-color`, `box-shadow`, and `border-color` for a smooth state change.

## Reduced Motion

The `is-scrolled` class still gets toggled — it's a CSS state change, not a JS animation. The transition itself is short (250ms) and unobtrusive. Reduced-motion users still see the visual contrast without parallax noise.

## Files Touched

- `frontend/src/pages/Landing.tsx` — `.site-nav` class on `<header>`, inline `<style>` block, ScrollTrigger inside the page's `useGSAP`.
