import { Navigate, Outlet, useLocation } from 'react-router-dom'

import type { Role } from '../api/auth.ts'
import { useAuth } from '../auth/context.ts'

interface ProtectedRouteProps {
  /** Minimum role required. Defaults to any authenticated user. */
  role?: Role
}

/**
 * Route guard.
 *
 * Renders nothing while the stored session is being verified, redirects to
 * /login (remembering where you were headed) when signed out, and shows a
 * refusal when signed in without the required role.
 *
 * This gates the UI only — every endpoint re-checks the role server-side.
 */
export function ProtectedRoute({ role = 'member' }: ProtectedRouteProps) {
  const { user, initialising, can } = useAuth()
  const location = useLocation()

  if (initialising) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-(--surface)">
        <p className="text-sm text-(--surface-muted)">Restoring your session…</p>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  if (!can(role)) {
    return (
      <section className="flex flex-col items-start gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Not available to your role</h1>
        <p className="max-w-prose text-sm text-(--surface-muted)">
          This page needs the <strong>{role}</strong> role. You are signed in as{' '}
          <strong>{user.username}</strong> ({user.role_display}).
        </p>
      </section>
    )
  }

  return <Outlet />
}
