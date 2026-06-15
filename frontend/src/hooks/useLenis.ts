import { useEffect } from 'react'
import Lenis from 'lenis'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

/**
 * Global smooth-scroll. Mount once at the top of a page. Hooks Lenis into
 * `gsap.ticker` so ScrollTrigger updates stay in lock-step with the
 * inertial scroll position — no jitter when both run together.
 *
 * Respects `prefers-reduced-motion: reduce` — bypasses Lenis entirely so
 * keyboard, screen-reader, and assistive-tech users keep native scrolling.
 *
 * Tear-down is important: each Lenis instance attaches wheel + touchmove
 * listeners on `document`. Forgetting to destroy on unmount stacks
 * listeners on every SPA navigation and burns CPU.
 */
export function useLenis() {
  useEffect(() => {
    if (typeof window === 'undefined') return

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) return

    const lenis = new Lenis({
      // Standard easing curve — fast at start, settles cleanly.
      duration: 1.1,
      easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      // Mobile inertia stays opt-in via gestureOrientation, otherwise
      // native touch scroll fights the lib on iOS.
      smoothWheel: true,
    })

    function raf(time: number) {
      lenis.raf(time * 1000)
    }
    gsap.ticker.add(raf)
    gsap.ticker.lagSmoothing(0)

    // Tell ScrollTrigger when Lenis updates the scroll position.
    lenis.on('scroll', ScrollTrigger.update)

    return () => {
      gsap.ticker.remove(raf)
      lenis.destroy()
    }
  }, [])
}
