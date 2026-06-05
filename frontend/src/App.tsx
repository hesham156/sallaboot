import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spinner } from '@heroui/react'
import { getToken, getStoreId, getIsSuper } from './api'
import Login from './pages/Login'
import Landing from './pages/Landing'
// Lazy-load the authenticated app shells so the login screen loads fast.
const StoresList     = lazy(() => import('./pages/StoresList'))
const StoreDashboard = lazy(() => import('./pages/StoreDashboard'))
const PrivacyPolicy  = lazy(() => import('./pages/PrivacyPolicy'))
const TermsOfService = lazy(() => import('./pages/TermsOfService'))
const DataDeletion   = lazy(() => import('./pages/DataDeletion'))


function RequireSuper({ children }: { children: JSX.Element }) {
  const token = getToken()
  const isSuper = getIsSuper()
  if (!token || !isSuper) return <Navigate to="/login" replace />
  return children
}

// Store dashboard is for store owners only — super admins are blocked
function RequireStoreOwner({ children }: { children: JSX.Element }) {
  const token = getToken()
  const isSuper = getIsSuper()
  if (!token) return <Navigate to="/login" replace />
  if (isSuper) return <Navigate to="/admin" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
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

        {/* Per-store dashboard — store owners only, admins blocked */}
        <Route
          path="/store/:storeId/*"
          element={
            <RequireStoreOwner>
              <StoreDashboard />
            </RequireStoreOwner>
          }
        />

        {/* Auto-redirect: authenticated → dashboard, guest → landing */}
        <Route
          path="*"
          element={
            <Navigate
              to={
                getToken()
                  ? getIsSuper()
                    ? '/admin'
                    : `/store/${getStoreId()}`
                  : '/landing'
              }
              replace
            />
          }
        />
      </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
