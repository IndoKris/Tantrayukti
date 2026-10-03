import { createBrowserRouter } from 'react-router-dom'

import { AppLayout } from './components/AppLayout.tsx'
import Community from './pages/Community.tsx'
import Dashboard from './pages/Dashboard.tsx'
import Insights from './pages/Insights.tsx'
import NotFound from './pages/NotFound.tsx'
import Profile from './pages/Profile.tsx'
import Reports from './pages/Reports.tsx'
import Spaces from './pages/Spaces.tsx'
import Welcome from './pages/Welcome.tsx'

/**
 * Application routes.
 *
 * `/welcome` keeps the original Vite starter page reachable; everything else is
 * rendered inside the EcoTrack layout shell. Phase 4 wraps these in the
 * protected-route helper once JWT auth exists.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'spaces', element: <Spaces /> },
      { path: 'insights', element: <Insights /> },
      { path: 'reports', element: <Reports /> },
      { path: 'community', element: <Community /> },
      { path: 'profile', element: <Profile /> },
      { path: '*', element: <NotFound /> },
    ],
  },
  // Outside the shell: the preserved starter page renders its own full-page column.
  { path: '/welcome', element: <Welcome /> },
])
