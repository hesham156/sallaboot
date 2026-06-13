import { motion, useReducedMotion, type Variants } from 'framer-motion'
import type { ReactNode } from 'react'

/**
 * Shared scroll-reveal primitives for the marketing site.
 *
 * - AnimatedSection: single fade + slide on enter
 * - StaggerContainer + StaggerItem: list reveals one child at a time
 * - fadeUpVariants / staggerVariants: raw variants to attach to motion.h1 etc.
 *   without an extra wrapper div
 *
 * All primitives honor `prefers-reduced-motion`: distance collapses to 0 and
 * duration shortens to 0.15s so users who opted out still get a quick fade
 * instead of a jarring snap.
 */

// Expo-out — the gold-standard "Apple feel" curve: starts fast, lands like
// silk. Pairs with a slightly longer duration and a smaller distance to
// avoid the snap-in effect that linear/quad curves give at higher speeds.
const EASE = [0.16, 1, 0.3, 1] as const
const DURATION = 0.85
const REDUCED_DURATION = 0.2
const DISTANCE = 24
const STAGGER = 0.1
// Trigger slightly before the element is fully in frame so it animates
// while the user is still scrolling toward it — feels anticipatory, not
// reactive. amount=0.15 means "fire when 15% of the element is visible".
const VIEWPORT_AMOUNT = 0.15

type Direction = 'up' | 'left' | 'right'

function offsetFor(direction: Direction, distance: number) {
  if (direction === 'up') return { y: distance, x: 0 }
  if (direction === 'left') return { x: -distance, y: 0 }
  return { x: distance, y: 0 }
}

/* ── Raw variants (for direct use on motion.h1 / motion.p / etc.) ── */

export const fadeUpVariants: Variants = {
  hidden: { opacity: 0, y: DISTANCE },
  visible: { opacity: 1, y: 0, transition: { duration: DURATION, ease: EASE } },
}

export const staggerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: STAGGER, delayChildren: 0.05 } },
}

/* ── AnimatedSection ── */

interface AnimatedSectionProps {
  children: ReactNode
  direction?: Direction
  delay?: number
  className?: string
  once?: boolean
}

export function AnimatedSection({
  children,
  direction = 'up',
  delay = 0,
  className,
  once = true,
}: AnimatedSectionProps) {
  const reduce = useReducedMotion()
  const distance = reduce ? 0 : DISTANCE
  const duration = reduce ? REDUCED_DURATION : DURATION
  const offset = offsetFor(direction, distance)

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, ...offset }}
      whileInView={{ opacity: 1, x: 0, y: 0 }}
      viewport={{ once, amount: VIEWPORT_AMOUNT }}
      transition={{ duration, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  )
}

/* ── StaggerContainer ── */

interface StaggerContainerProps {
  children: ReactNode
  className?: string
  once?: boolean
}

export function StaggerContainer({ children, className, once = true }: StaggerContainerProps) {
  const reduce = useReducedMotion()
  const variants: Variants = reduce
    ? { hidden: {}, visible: { transition: { staggerChildren: 0, delayChildren: 0 } } }
    : staggerVariants

  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once, amount: VIEWPORT_AMOUNT }}
      variants={variants}
    >
      {children}
    </motion.div>
  )
}

/* ── StaggerItem ── */

interface StaggerItemProps {
  children: ReactNode
  direction?: Direction
  className?: string
}

export function StaggerItem({ children, direction = 'up', className }: StaggerItemProps) {
  const reduce = useReducedMotion()
  const distance = reduce ? 0 : DISTANCE
  const duration = reduce ? REDUCED_DURATION : DURATION
  const offset = offsetFor(direction, distance)

  const variants: Variants = {
    hidden: { opacity: 0, ...offset },
    visible: { opacity: 1, x: 0, y: 0, transition: { duration, ease: EASE } },
  }

  return (
    <motion.div className={className} variants={variants}>
      {children}
    </motion.div>
  )
}
