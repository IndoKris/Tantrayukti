import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  fetchMe,
  hasRoleAtLeast,
  hasStoredSession,
  login as loginRequest,
  logout as logoutRequest,
  type Role,
  type User,
} from '../api/auth.ts'
import { setSessionExpiredHandler } from '../api/client.ts'
import { AuthContext, type AuthContextValue } from './context.ts'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // Only block the first paint when there is actually a session to restore.
  const [initialising, setInitialising] = useState(hasStoredSession)

  const logout = useCallback(() => {
    logoutRequest()
    setUser(null)
  }, [])

  // A failed refresh anywhere in the app ends the session here.
  useEffect(() => {
    setSessionExpiredHandler(() => setUser(null))
    return () => setSessionExpiredHandler(() => {})
  }, [])

  // Restore the session on first load: a stored token is only trusted once
  // /api/auth/me/ confirms it.
  useEffect(() => {
    if (!hasStoredSession()) return

    let cancelled = false

    fetchMe()
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch(() => {
        if (!cancelled) logoutRequest()
      })
      .finally(() => {
        if (!cancelled) setInitialising(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    setUser(await loginRequest(username, password))
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      initialising,
      login,
      logout,
      can: (role: Role) => hasRoleAtLeast(user, role),
    }),
    [user, initialising, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
