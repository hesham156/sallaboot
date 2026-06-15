# Animation Tasks - sallaboot

## Workflow Rules

- Source Of Truth: .gsap artifacts + the actual code on disk
- Execution Style: one phase at a time
- Parallelism Rule: do not implement multiple major sections in one unchecked pass
- Update Rule: after each phase, update page, plan, and tasks artifacts
- Active Phase: P02

## Current Queue

| Phase | Page | Section | Goal | Status |
|---|---|---|---|---|
| P00 | landing | Smooth scroll | Lenis hooked to gsap.ticker, ScrollTrigger sync | Done |
| P11 | landing | Hero | Cinematic GSAP timeline entrance + floating cards + scroll parallax | Done |
| P01 | landing | Navigation | Navbar bg/shadow deepens past hero (ScrollTrigger) | Done |
| P03 | landing | Stats | Count-up on scroll-enter (ScrollTrigger, Arabic digits) | Done |
| P02 | landing | Feature Grid | Staggered ScrollTrigger card reveal + hover depth | Next |
| P05 | landing | How It Works | Step-by-step reveal with connector line draw | Planned |
| P06 | landing | FAQ | Accordion height animation (GSAP height tween) | Planned |
| P10 | landing | CTA | Shimmer/emphasis on gradient CTA section | Planned |
| P04 | landing | Testimonials | N/A — no testimonials section on this page | Skip |
| P07 | landing | Pricing | N/A — no pricing section on this page | Skip |
| P08 | landing | Logos | N/A — no logo cloud on this page | Skip |
| P09 | landing | Form | N/A — no standalone form on this page | Skip |
| P12 | landing | Showcase | N/A — no showcase section on this page | Skip |

## Active Phase Checklist (P02 Feature Grid)

- [ ] Open `.gsap/phases/landing/p02-feature-grid.md`.
- [ ] Replace Framer Motion stagger on `.grid sm:grid-cols-2 lg:grid-cols-3` with GSAP ScrollTrigger batch.
- [ ] Each card: opacity 0 + y 20 → 1 + 0, stagger 80ms, fires once.
- [ ] Add subtle hover depth (translate-y on hover already in Tailwind classes — leave it, don't fight it).
- [ ] Verify reduced motion: cards visible immediately, no scroll-trigger delay.
- [ ] Update plan, page, and phase artifacts.

## Notes On Drift

Earlier session(s) wrote "Done" to several phases before the changes were
fully committed. A subsequent `git checkout -- frontend/` reverted them,
so the artifacts and the code disagreed. This file now reflects what
the code on disk actually contains; if you see a future mismatch, the
code is the source of truth.
