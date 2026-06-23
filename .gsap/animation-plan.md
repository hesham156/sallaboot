# Animation Plan - sallaboot

## Workflow State

- Current Mode: gsap-new
- Resume State: Discovery complete, phased execution pending
- Last Updated By:
- Suggested Next Command: Implement P01 only, then update all .gsap artifacts.
- Active Phase: P01

## Target Scope

- Pages:
- Primary Goal:
- Constraints:

## Implementation Order

1. Read .gsap artifacts
2. Inspect current code
3. Resolve missing decisions
4. Implement section by section
5. Verify mobile and reduced motion
6. Update artifacts after changes

## Recipes By Section

| Page | Section | Recipe | Status | Notes |
|---|---|---|---|---|
| landing | Navigation | navbar polish on scroll | Planned | Make the Navigation section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Feature Grid | staggered card reveal + hover depth | Planned | Make the Feature Grid section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Stats | count-up on enter | Planned | Make the Stats section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Testimonials | quote reveal + soft carousel polish | Planned | Make the Testimonials section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Timeline | step-by-step reveal | Planned | Make the Timeline section feel intentional, modern, and aligned with the page hierarchy. |
| landing | FAQ | accordion timing polish | Planned | Make the FAQ section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Pricing | pricing-card emphasis + trust hierarchy | Planned | Make the Pricing section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Logos | logo cloud drift + credibility polish | Planned | Make the Logos section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Team | profile stagger + soft hover depth | Planned | Make the Team section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Form | field-focus polish + success transitions | Planned | Make the Form section feel intentional, modern, and aligned with the page hierarchy. |
| landing | CTA | cta emphasis + magnetic hover | Planned | Make the CTA section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Hero | hero-text-reveal + layered media parallax | Planned | Make the Hero section feel intentional, modern, and aligned with the page hierarchy. |
| landing | Showcase | parallax showcase or marquee | Planned | Make the Showcase section feel intentional, modern, and aligned with the page hierarchy. |

## Phases

| Phase | Page | Section | Objective | Recipe | Status |
|---|---|---|---|---|---|
| P01 | landing | Navigation | Make the Navigation section feel intentional, modern, and aligned with the page hierarchy. | navbar polish on scroll | Planned |
| P02 | landing | Feature Grid | Make the Feature Grid section feel intentional, modern, and aligned with the page hierarchy. | staggered card reveal + hover depth | Planned |
| P03 | landing | Stats | Make the Stats section feel intentional, modern, and aligned with the page hierarchy. | count-up on enter | Planned |
| P04 | landing | Testimonials | Make the Testimonials section feel intentional, modern, and aligned with the page hierarchy. | quote reveal + soft carousel polish | Planned |
| P05 | landing | Timeline | Make the Timeline section feel intentional, modern, and aligned with the page hierarchy. | step-by-step reveal | Planned |
| P06 | landing | FAQ | Make the FAQ section feel intentional, modern, and aligned with the page hierarchy. | accordion timing polish | Planned |
| P07 | landing | Pricing | Make the Pricing section feel intentional, modern, and aligned with the page hierarchy. | pricing-card emphasis + trust hierarchy | Planned |
| P08 | landing | Logos | Make the Logos section feel intentional, modern, and aligned with the page hierarchy. | logo cloud drift + credibility polish | Planned |
| P09 | landing | Team | Make the Team section feel intentional, modern, and aligned with the page hierarchy. | profile stagger + soft hover depth | Planned |
| P10 | landing | Form | Make the Form section feel intentional, modern, and aligned with the page hierarchy. | field-focus polish + success transitions | Planned |
| P11 | landing | CTA | Make the CTA section feel intentional, modern, and aligned with the page hierarchy. | cta emphasis + magnetic hover | Planned |
| P12 | landing | Hero | Make the Hero section feel intentional, modern, and aligned with the page hierarchy. | hero-text-reveal + layered media parallax | Planned |
| P13 | landing | Showcase | Make the Showcase section feel intentional, modern, and aligned with the page hierarchy. | parallax showcase or marquee | Planned |

## Validation Checklist

- [ ] Reduced motion covered
- [ ] Mobile-heavy effects reviewed
- [ ] Existing code inspected before changes
- [ ] Page artifact updated after implementation
- [ ] Discovery questions resolved or consciously deferred
- [ ] Tasks file created or refreshed
- [ ] Phase files created or refreshed

## Workflow Snapshot - landing

- Mode: gsap-new
- Framework: react
- Package Manager: npm
- Existing Motion Stack: Framer Motion, GSAP, Lenis, Three.js
- Matched Files: api.ts, App.tsx, ErrorBoundary.tsx, ui.tsx, useSEO.ts, main.tsx, BlogPost.tsx, ErrorPage.tsx
- Inferred Product Type: Marketing Site, Booking Platform, Dashboard

## Implementation Plan - landing

- Read .gsap artifacts before editing code.
- Work in one major section phase at a time.
- Finish hero or top-priority story beat before supporting sections.
- Add spectacle only where the story earns it.
- Update phase, tasks, and page artifacts after each section.

## Detected Project Signals - landing

- Sections: Navigation, Feature Grid, Stats, Testimonials, Timeline, FAQ, Pricing, Logos, Team, Form, CTA, Hero, Showcase
- Structure Patterns: Data visualization, Data table, Search and filtering, Auth surface, Calendar or booking flow, Repeated collection render, Overlay interactions, Sticky positioning, Video surface, Tabbed interface
- Selector Samples: flex items-center justify-center min-h-screen bg-background, space-y-1.5, flex items-center gap-1 text-sm font-semibold text-default-700 px-0.5, text-danger text-sm leading-none, text-[11px] font-normal text-default-400 mr-0.5, flex items-center gap-1 text-[11px] text-danger px-0.5, flex items-start gap-3, min-w-0 flex-1, font-bold text-sm text-foreground leading-tight, text-[11px] text-default-400 mt-0.5 leading-relaxed
- Infrastructure: None strongly inferred
- Recommendations:
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
  - Should charts and metrics animate softly for readability, or should they feel more dramatic and presentational?
  - Should the hero motion feel premium and cinematic, or quiet and product-focused?
  - Should forms use only subtle focus polish, or do you want stronger field and success-state motion?
  - Should partner or client logos stay subtle, or should they get motion emphasis as social proof?
  - Should pricing cards feel calm and trustworthy, or more high-conversion and attention-grabbing?
  - Should repeated cards share one reveal system, or should featured cards feel more premium than the rest?
- Constraints:
  - 3D surfaces need strong mobile fallbacks.
  - Data-heavy screens need clarity-first motion and low distraction.
  - Forms and auth flows need utility-first motion, not theatrical timing.
