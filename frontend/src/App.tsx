import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spinner } from '@heroui/react'
import { getToken, getIsSuper } from './api'
import Login from './pages/Login'
import Landing from './pages/Landing'
import ErrorPage from './pages/ErrorPage'
import ErrorBoundary from './components/ErrorBoundary'
// Lazy-load the authenticated app shells so the login screen loads fast.
const StoresList     = lazy(() => import('./pages/StoresList'))
const StoreDashboard = lazy(() => import('./pages/StoreDashboard'))
const PlatformOps    = lazy(() => import('./pages/PlatformOps'))
const AuditLog       = lazy(() => import('./pages/AuditLog'))
const PrivacyPolicy  = lazy(() => import('./pages/PrivacyPolicy'))
const TermsOfService = lazy(() => import('./pages/TermsOfService'))
const DataDeletion   = lazy(() => import('./pages/DataDeletion'))


function RequireSuper({ children }: { children: JSX.Element }) {
  const token = getToken()
  const isSuper = getIsSuper()
  if (!token) return <Navigate to="/login" replace />
  // Authenticated but not a super-admin → 403 rather than silent redirect.
  // A silent redirect to /admin would loop right back here.
  if (!isSuper) return <ErrorPage code={403} />
  return children
}

// Store dashboard — owner OR super admin (super sees an "impersonation"
// banner so they don't forget the access is logged). We do NOT block
// super here: their use case is exactly to drop into a store to debug
// or help a merchant. Sensitive reads (customer conversations, live
// streams) are gated separately with reason + audit.
function RequireStoreOwner({ children }: { children: JSX.Element }) {
  const token = getToken()
  if (!token) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Suspense fallback={
          <div className="flex items-center justify-center min-h-screen bg-background">
            <Spinner size="lg" color="primary" label="جاري التحميل..." />
          </div>
        }>
        <Routes>
          {/* Public landing page — always accessible, even when logged in */}
          <Route path="/" element={<Landing />} />
          <Route path="/landing" element={<Landing />} />

          <Route path="/login" element={<Login />} />

          {/* Public Policy Pages */}
          <Route path="/privacy" element={<PrivacyPolicy />} />
          <Route path="/terms" element={<TermsOfService />} />
          <Route path="/data-deletion" element={<DataDeletion />} />

          {/* Super-admin: all stores */}
          <Route
            path="/admin"
            element={
              <RequireSuper>
                <StoresList />
              </RequireSuper>
            }
          />
          <Route
            path="/admin/platform-ops"
            element={
              <RequireSuper>
                <PlatformOps />
              </RequireSuper>
            }
          />
          <Route
            path="/admin/audit-log"
            element={
              <RequireSuper>
                <AuditLog />
              </RequireSuper>
            }
          />

          {/* Per-store dashboard — store owners only, admins blocked */}
          <Route
            path="/store/:storeId/*"
            element={
              <RequireStoreOwner>
                <StoreDashboard />
              </RequireStoreOwner>
            }
          />

          {/* Explicit error pages, reachable via /error/404, /error/500, etc.
              The backend's HTML fallback handler routes browser navigation
              for unknown server paths into these. Bare /error (no code)
              defaults to 404 — same component, fallback meta. */}
          <Route path="/error/:code" element={<ErrorPage />} />
          <Route path="/error"        element={<ErrorPage code={404} />} />

          {/* Unknown route → 404 page. Previously this silently bounced
              to landing/dashboard which hid mistyped URLs. */}
          <Route path="*" element={<ErrorPage code={404} />} />
        </Routes>
        </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
  )
}
