# Animation Spec - sallaboot

## Workflow State

- Owner Workflow: gsap-refactor
- Source Of Truth: .gsap artifacts
- Resume Rule: Read these files before asking new questions

## Philosophy

- Personality: Subtle & Professional
- Density: Moderate
- Scroll Behavior: Scroll-triggered reveals

## Global Effects

- [ ] Smooth scroll
- [ ] Magnetic buttons
- [ ] Page transitions
- [ ] Parallax images

## Performance Rules

- Device Priority: Mobile-first
- Reduced Motion: Required
- Heavy Effects On Mobile: Disabled unless intentionally approved
- Preferred Animated Properties: transform, opacity

## Missing Decisions

- Brand references:
- Sections needing strongest emphasis:
- Elements to avoid over-animating:

## Project Intelligence

- Inferred Archetypes: Marketing Site, Dashboard, Booking Platform
- Supporting Infrastructure:
  - None strongly inferred
- Project Constraints:
  - Data-heavy screens need clarity-first motion and low distraction.
  - Forms and auth flows need utility-first motion, not theatrical timing.

## Interview Strategy

- Interview Mode: targeted-discovery
- Priority Categories: Technical Stack, Section Behavior, Creative Direction, Workflow Clarification
- Priority Questions:
  - Should the workflow install GSAP now, or only prepare the spec and phased plan?
  - Should charts and metrics animate softly for readability, or should they feel more dramatic and presentational?
  - Should the hero motion feel premium and cinematic, or quiet and product-focused?
  - Do you want smooth scrolling like Lenis, or should native scrolling stay untouched?
  - Should forms use only subtle focus polish, or do you want stronger field and success-state motion?
  - Should partner or client logos stay subtle, or should they get motion emphasis as social proof?

## Spec-Driven Rules

- Planning must happen before implementation.
- Work must be split into phases with one major section per phase.
- Each phase must have explicit reduced-motion and mobile downgrade notes.
- The next agent should be able to resume from artifacts alone.

## Discovery Snapshot

- Framework: react
- Package Manager: npm
- Packages:
  - react@^18.3.1
  - tailwindcss@^3.4.9
  - framer-motion@^11.3.0
  - typescript@^5.5.3
- Routes Detected: None detected

## Brand And Design Signals

- Colors:
  - #14b8a6
  - #06b6d4
  - #cbd5e0
  - #a0aec0
  - rgba(45, 55, 72, 0.06)
  - rgba(45, 55, 72, 0.08)
  - rgba(20,184,166,0.12)
  - rgba(22,163,74,0.12)
  - rgba(6,182,212,0.12)
  - rgba(217,119,6,0.12)
- Fonts:
  - 'Cairo', sans-serif !important
- Tone Hints:
  - ai
- CSS Variables:
  - None detected
- Visual Direction:
  - gradient-rich
  - rounded-ui
  - depth-layering
- Blur Usage Signals: 0
- Backdrop Filter Signals: 0

## Questions To Resolve

- Should the workflow install GSAP now, or only prepare the spec and phased plan?
- Should charts and metrics animate softly for readability, or should they feel more dramatic and presentational?
- Should the hero motion feel premium and cinematic, or quiet and product-focused?
- Do you want smooth scrolling like Lenis, or should native scrolling stay untouched?
- Should forms use only subtle focus polish, or do you want stronger field and success-state motion?
- Should partner or client logos stay subtle, or should they get motion emphasis as social proof?

## Phase Strategy

- Active Page: landing
- Rule: implement one major section per phase.
- Planned Phase Count: 12
- First Phase: P01 - Navigation
