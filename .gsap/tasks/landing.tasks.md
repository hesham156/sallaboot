# Animation Tasks - sallaboot

## Workflow Rules

- Source Of Truth: .gsap artifacts + the actual code on disk
- Execution Style: one phase at a time
- Parallelism Rule: do not implement multiple major sections in one unchecked pass
- Update Rule: after each phase, update page, plan, and tasks artifacts
- Active Phase: P01

## Current Queue

| Phase | Page | Section | Goal | Status |
|---|---|---|---|---|
| P01 | landing | Navigation | Make the Navigation section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P02 | landing | Feature Grid | Make the Feature Grid section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P03 | landing | Stats | Make the Stats section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P04 | landing | Testimonials | Make the Testimonials section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P05 | landing | Timeline | Make the Timeline section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P06 | landing | FAQ | Make the FAQ section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P07 | landing | Pricing | Make the Pricing section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P08 | landing | Logos | Make the Logos section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P09 | landing | Team | Make the Team section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P10 | landing | Form | Make the Form section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P11 | landing | CTA | Make the CTA section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P12 | landing | Hero | Make the Hero section feel intentional, modern, and aligned with the page hierarchy. | Planned |
| P13 | landing | Showcase | Make the Showcase section feel intentional, modern, and aligned with the page hierarchy. | Planned |

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

## Active Phase Checklist

- [ ] Open `.gsap/phases/landing/p01-navigation.md`.
- [ ] Implement only the Navigation section in this pass.
- [ ] Verify reduced motion and mobile behavior.
- [ ] Update plan, page, and phase artifacts.
- [ ] Only then move to the next phase.
