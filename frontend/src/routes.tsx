import { createBrowserRouter } from 'react-router-dom'

import { AppLayout } from './components/AppLayout.tsx'
import { ProtectedRoute } from './components/ProtectedRoute.tsx'
import Community from './pages/Community.tsx'
import Dashboard from './pages/Dashboard.tsx'
import Insights from './pages/Insights.tsx'
import MlMetrics from './pages/MlMetrics.tsx'
import Login from './pages/Login.tsx'
import NotFound from './pages/NotFound.tsx'
import Profile from './pages/Profile.tsx'
import Reports from './pages/Reports.tsx'
import Spaces from './pages/Spaces.tsx'
import Welcome from './pages/Welcome.tsx'

/**
 * Application routes.
 *
 * Everything under `/` sits behind `ProtectedRoute`, which redirects to /login
 * when signed out. `/login` and `/welcome` are public; `/welcome` keeps the
 * original Vite starter page reachable.
 */
export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  // Outside the shell: the preserved starter page renders its own full-page column.
  { path: '/welcome', element: <Welcome /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <Dashboard /> },
          { path: 'spaces', element: <Spaces /> },
          { path: 'insights', element: <Insights /> },
          { path: 'insights/metrics', element: <MlMetrics /> },
          { path: 'reports', element: <Reports /> },
          { path: 'community', element: <Community /> },
          { path: 'profile', element: <Profile /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
])
