import { Component, type ErrorInfo, type ReactNode } from 'react'
import ErrorPage from '../pages/ErrorPage'

interface State {
  error: Error | null
}

// One-shot session flag so we never reload more than once per tab. If the
// fresh index.html ALSO can't load its chunks (e.g. the deploy is
// genuinely broken, not just stale), we fall through to the 500 page on
// the second crash instead of spinning forever.
const RELOAD_FLAG = '__sallabot_chunk_reloaded__'

/**
 * Recognise the "stale build" pattern. After a new deploy, the browser
 * may have cached the previous index.html, whose <script src=…> tags
 * point at chunk hashes that no longer exist on the server. Vite's
 * runtime then throws this exact message inside React.lazy(). One full
 * page reload picks up the fresh index.html (the backend marks it
 * Cache-Control: no-store) and resolves the issue.
 *
 * Match on the message — different browsers phrase it slightly
 * differently ("Failed to fetch dynamically imported module" / "error
 * loading dynamically imported module" / "Importing a module script
 * failed").
 */
function isChunkLoadError(err: Error | null): boolean {
  if (!err) return false
  const msg = String(err.message || '').toLowerCase()
  return (
    msg.includes('dynamically imported module') ||
    msg.includes('loading chunk')               ||
    msg.includes('importing a module script')   ||
    msg.includes('module script failed')
  )
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

    // Self-heal on stale-deploy chunk errors: reload once so the browser
    // refetches index.html (which is no-store on the backend) and gets the
    // current chunk hashes. The session flag guards against infinite loops
    // if the new build is genuinely broken — second crash falls through to
    // the styled 500 page.
    if (isChunkLoadError(error)) {
      try {
        if (!sessionStorage.getItem(RELOAD_FLAG)) {
          sessionStorage.setItem(RELOAD_FLAG, '1')
          console.warn('[ErrorBoundary] Stale chunk detected — reloading once to pick up new build')
          window.location.reload()
          return
        }
      } catch {
        // sessionStorage can be disabled (private mode quirks). Fall
        // through to the friendly 500 page rather than risking a loop.
      }
    }
  }

  render() {
    if (this.state.error) {
      const isStaleDeploy = isChunkLoadError(this.state.error)
      return (
        <ErrorPage
          code={500}
          message={
            import.meta.env.DEV
              ? `[تطوير فقط] ${this.state.error.message}`
              : isStaleDeploy
                ? 'تم تحديث النظام للتو. اضغط "حاول مرة أخرى" لتحميل النسخة الجديدة.'
                : undefined
          }
        />
      )
    }
    return this.props.children
  }
}
