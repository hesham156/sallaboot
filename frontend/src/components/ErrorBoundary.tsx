import { Component, type ErrorInfo, type ReactNode } from 'react'
import ErrorPage from '../pages/ErrorPage'

interface State {
  error: Error | null
}

/**
 * Top-level boundary that catches synchronous React render / lifecycle
 * errors and shows the same 500 page the server would have shown. Async
 * errors (thrown inside event handlers, promises) are NOT caught here —
 * those propagate to the unhandledrejection listener wired in main.tsx.
 *
 * Why catch at the top instead of per-route: a render crash in a feature
 * area would otherwise white-screen the whole app. One boundary at the
 * router root gives every route the same "something went wrong" UX
 * without sprinkling try/catches through the tree.
 */
export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log to console so developers see the stack — Sentry/etc would hook
    // in here when we add observability (M15).
    console.error('[ErrorBoundary] React render crashed:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorPage
          code={500}
          message={
            // In dev, show the actual exception message so debugging is
            // fast. In production builds Vite drops the dev branch via
            // import.meta.env.DEV constant folding, leaving the friendly
            // copy intact.
            import.meta.env.DEV
              ? `[تطوير فقط] ${this.state.error.message}`
              : undefined
          }
        />
      )
    }
    return this.props.children
  }
}
