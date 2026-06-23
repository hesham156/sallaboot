# Page Animation Spec - landing

## Page

- Page Route: /landing
- Source File: D:/saas/sallaboot/frontend/src/api.ts
- Page Status: Needs phased implementation plan

## Resume State

- Next Agent Action: open phase P01 and implement only that section.
- Blocking Questions: Should charts and metrics animate softly for readability, or should they feel more dramatic and presentational? | Should the hero motion feel premium and cinematic, or quiet and product-focused? | Should forms use only subtle focus polish, or do you want stronger field and success-state motion? | Should partner or client logos stay subtle, or should they get motion emphasis as social proof? | Should pricing cards feel calm and trustworthy, or more high-conversion and attention-grabbing? | Should repeated cards share one reveal system, or should featured cards feel more premium than the rest?
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

- Inferred Product Type: Marketing Site, Booking Platform, Dashboard
- Motion Constraints:
  - 3D surfaces need strong mobile fallbacks.
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
| P09 | Team | profile stagger + soft hover depth | Planned | Make the Team section feel intentional, modern, and aligned with the page hierarchy. |
| P10 | Form | field-focus polish + success transitions | Planned | Make the Form section feel intentional, modern, and aligned with the page hierarchy. |
| P11 | CTA | cta emphasis + magnetic hover | Planned | Make the CTA section feel intentional, modern, and aligned with the page hierarchy. |
| P12 | Hero | hero-text-reveal + layered media parallax | Planned | Make the Hero section feel intentional, modern, and aligned with the page hierarchy. |
| P13 | Showcase | parallax showcase or marquee | Planned | Make the Showcase section feel intentional, modern, and aligned with the page hierarchy. |

## Discovery Snapshot

- Matched Files: api.ts, App.tsx, ErrorBoundary.tsx, ui.tsx, useSEO.ts, main.tsx, BlogPost.tsx, ErrorPage.tsx
- Sections Detected: Navigation, Feature Grid, Stats, Testimonials, Timeline, FAQ, Pricing, Logos, Team, Form, CTA, Hero, Showcase
- Repeated Components: AuthResponse, StoreInfo, Conversation, Analytics, AIConfig, Record, TokenStatus, SupportAccessGrant, BlogPost, Campaign
- Structure Patterns: Data visualization, Data table, Search and filtering, Auth surface, Calendar or booking flow, Repeated collection render, Overlay interactions, Sticky positioning, Video surface, Tabbed interface
- Selector Samples: flex items-center justify-center min-h-screen bg-background, space-y-1.5, flex items-center gap-1 text-sm font-semibold text-default-700 px-0.5, text-danger text-sm leading-none, text-[11px] font-normal text-default-400 mr-0.5, flex items-center gap-1 text-[11px] text-danger px-0.5, flex items-start gap-3, min-w-0 flex-1
