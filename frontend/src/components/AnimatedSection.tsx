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

const EASE = [0.25, 0.46, 0.45, 0.94] as const
const DURATION = 0.55
const REDUCED_DURATION = 0.15
const DISTANCE = 40
const VIEWPORT_MARGIN = '-80px'

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
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
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
      viewport={{ once, margin: VIEWPORT_MARGIN }}
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
      viewport={{ once, margin: VIEWPORT_MARGIN }}
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
