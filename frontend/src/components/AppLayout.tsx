import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/context.ts'
import { ApiStatusBadge } from './ApiStatusBadge.tsx'

interface NavItem {
  to: string
  label: string
  /** Match the path exactly, so the index route is not active on every child route. */
  end?: boolean
}

const navItems: readonly NavItem[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/spaces', label: 'Spaces' },
  { to: '/insights', label: 'Insights' },
  { to: '/reports', label: 'Reports' },
  { to: '/community', label: 'Community' },
  { to: '/profile', label: 'Profile' },
]

function navLinkClass({ isActive }: { isActive: boolean }): string {
  const base =
    'block rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500'
  return isActive
    ? `${base} bg-eco-600 text-white`
    : `${base} text-(--surface-muted) hover:bg-(--surface) hover:text-(--surface-text)`
}

/** Signed-in user and sign-out control. */
function UserMenu() {
  const { user, logout } = useAuth()
  if (!user) return null

  return (
    <div className="flex items-center gap-3 border-t border-(--surface-border) pt-4 lg:mt-6">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{user.username}</p>
        <p className="text-xs text-(--surface-muted)">{user.role_display}</p>
      </div>
      <button
        type="button"
        onClick={logout}
        className="rounded-lg border border-(--surface-border) px-2.5 py-1.5 text-xs font-medium text-(--surface-muted) transition-colors hover:text-(--surface-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
      >
        Sign out
      </button>
    </div>
  )
}

export function AppLayout() {
  return (
    <div className="min-h-svh bg-(--surface) text-(--surface-text) font-sans text-base">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 lg:flex-row lg:px-8">
        <header className="lg:w-56 lg:shrink-0">
          <div className="flex items-center justify-between gap-4 lg:flex-col lg:items-start">
            <div>
              <p className="text-lg font-semibold tracking-tight">
                Eco<span className="text-eco-600">Track</span>
              </p>
              <p className="text-xs text-(--surface-muted)">Energy, cost and CO&#8322;</p>
            </div>
            <ApiStatusBadge />
          </div>

          <nav aria-label="Main" className="mt-6">
            <ul className="flex flex-wrap gap-1 lg:flex-col">
              {navItems.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.end} className={navLinkClass}>
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <UserMenu />
        </header>

        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
