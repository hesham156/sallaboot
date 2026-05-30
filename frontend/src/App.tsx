import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { getToken, getStoreId, getIsSuper } from './api'
import Login from './pages/Login'
import StoresList from './pages/StoresList'
import StoreDashboard from './pages/StoreDashboard'

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
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/login/:storeId" element={<Login />} />

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
    </HashRouter>
  )
}
