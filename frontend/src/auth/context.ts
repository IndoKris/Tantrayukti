/**
 * Auth context and hook.
 *
 * Kept separate from `AuthContext.tsx` so that file exports only a component,
 * which is what React Fast Refresh requires.
 */

import { createContext, useContext } from 'react'

import type { Role, User } from '../api/auth.ts'

export interface AuthContextValue {
  user: User | null
  /** True until the stored session has been checked, so routes do not flash. */
  initialising: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  /** Role check for rendering only; the server re-checks every request. */
  can: (role: Role) => boolean
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside an <AuthProvider>')
  }
  return context
}
