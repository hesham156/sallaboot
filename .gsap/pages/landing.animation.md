# Page Animation Spec - landing

## Page

- Page Route: /landing
- Source File: D:/saas/sallaboot/frontend/src/api.ts
- Page Status: Needs phased refactor

## Resume State

- Next Agent Action: open phase P01 and implement only that section.
- Blocking Questions: Should the workflow install GSAP now, or only prepare the spec and phased plan? | Should charts and metrics animate softly for readability, or should they feel more dramatic and presentational? | Should the hero motion feel premium and cinematic, or quiet and product-focused? | Do you want smooth scrolling like Lenis, or should native scrolling stay untouched? | Should forms use only subtle focus polish, or do you want stronger field and success-state motion? | Should partner or client logos stay subtle, or should they get motion emphasis as social proof?
- Discovery Confidence: Medium unless the agent verifies source files manually.
- Active Phase: P01

## Sections

### Hero

- Type:
- Elements:
- Status: Not started

### Content Grid / Cards

- Type:
- Elements:
- Status: Not started

### Stats / Numbers

- Type:
- Elements:
- Status: Not started

### CTA / Footer

- Type:
- Elements:
- Status: Not started

## Mobile Rules

- Simplifications:
- Disabled Effects:

## Reduced Motion

- Fallback Behavior:

## Recommended Motion Directions

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

## Scenario Notes

- Inferred Product Type: Marketing Site, Dashboard, Booking Platform
- Motion Constraints:
  - Data-heavy screens need clarity-first motion and low distraction.
  - Forms and auth flows need utility-first motion, not theatrical timing.

## Phase Status

| Phase | Section | Recipe | Status | Notes |
|---|---|---|---|---|
| P01 | Navigation | navbar polish on scroll | Planned | Make the Navigation section feel intentional, modern, and aligned with the page hierarchy. |
| P02 | Feature Grid | staggered card reveal + hover depth | Planned | Make the Feature Grid section feel intentional, modern, and aligned with the page hierarchy. |
| P03 | Stats | count-up on enter | Planned | Make the Stats section feel intentional, modern, and aligned with the page hierarchy. |
| P04 | Testimonials | quote reveal + soft carousel polish | Planned | Make the Testimonials section feel intentional, modern, and aligned with the page hierarchy. |
| P05 | Timeline | step-by-step reveal | Planned | Make the Timeline section feel intentional, modern, and aligned with the page hierarchy. |
| P06 | FAQ | accordion timing polish | Planned | Make the FAQ section feel intentional, modern, and aligned with the page hierarchy. |
| P07 | Pricing | pricing-card emphasis + trust hierarchy | Planned | Make the Pricing section feel intentional, modern, and aligned with the page hierarchy. |
| P08 | Logos | logo cloud drift + credibility polish | Planned | Make the Logos section feel intentional, modern, and aligned with the page hierarchy. |
| P09 | Form | field-focus polish + success transitions | Planned | Make the Form section feel intentional, modern, and aligned with the page hierarchy. |
| P10 | CTA | cta emphasis + magnetic hover | Planned | Make the CTA section feel intentional, modern, and aligned with the page hierarchy. |
| P11 | Hero | hero-text-reveal + layered media parallax | Planned | Make the Hero section feel intentional, modern, and aligned with the page hierarchy. |
| P12 | Showcase | parallax showcase or marquee | Planned | Make the Showcase section feel intentional, modern, and aligned with the page hierarchy. |

## Discovery Snapshot

- Matched Files: api.ts, App.tsx, ErrorBoundary.tsx, useSEO.ts, main.tsx, BlogPost.tsx, ErrorPage.tsx, Landing.tsx
- Sections Detected: Navigation, Feature Grid, Stats, Testimonials, Timeline, FAQ, Pricing, Logos, Form, CTA, Hero, Showcase
- Repeated Components: StoreInfo, Conversation, Analytics, AIConfig, Record, TokenStatus, BlogPost, Navigate, ErrorPage, Suspense
- Structure Patterns: Data visualization, Data table, Search and filtering, Auth surface, Calendar or booking flow, Repeated collection render, Sticky positioning, Modal interactions, Sidebar or drawer
- Selector Samples: flex items-center justify-center min-h-screen bg-background, light text-foreground bg-background min-h-screen font-arabic, min-h-screen bg-white flex items-center justify-center text-slate-400, min-h-screen bg-white text-slate-800 font-sans pb-20 overflow-x-hidden, sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100, max-w-4xl mx-auto px-6 h-16 flex items-center justify-between, flex items-center gap-2.5, inline-flex items-center gap-2 text-sm font-bold text-slate-700 bg-white border border-slate-200 rounded-full px-5 py-2 hover:border-teal-300 hover:text-teal-600 shadow-sm transition-all
