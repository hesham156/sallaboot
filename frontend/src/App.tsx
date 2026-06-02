import { lazy, Suspense } from 'react'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spinner } from '@heroui/react'
import { getToken, getStoreId, getIsSuper } from './api'
import Login from './pages/Login'
// Lazy-load the authenticated app shells so the login screen loads fast.
const StoresList     = lazy(() => import('./pages/StoresList'))
const StoreDashboard = lazy(() => import('./pages/StoreDashboard'))

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = getToken()
  if (!token) return <Navigate to="/login" replace />
  return children
}

function RequireSuper({ children }: { children: JSX.Element }) {
  const token = getToken()
  const isSuper = getIsSuper()
  if (!token || !isSuper) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <HashRouter>
      <Suspense fallback={
        <div className="flex items-center justify-center min-h-screen bg-background">
          <Spinner size="lg" color="primary" label="جاري التحميل..." />
        </div>
      }>
      <Routes>
        <Route path="/login" element={<Login />} />

        {/* Super-admin: all stores */}
        <Route
          path="/"
          element={
            <RequireSuper>
              <StoresList />
            </RequireSuper>
          }
        />

        {/* Per-store dashboard */}
        <Route
          path="/store/:storeId/*"
          element={
            <RequireAuth>
              <StoreDashboard />
            </RequireAuth>
          }
        />

        {/* Auto-redirect based on stored auth */}
        <Route
          path="*"
          element={
            <Navigate
              to={
                getToken()
                  ? getIsSuper()
                    ? '/'
                    : `/store/${getStoreId()}`
                  : '/login'
              }
              replace
            />
          }
        />
      </Routes>
      </Suspense>
    </HashRouter>
  )
}
