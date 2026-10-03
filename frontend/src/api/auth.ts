/** Authentication endpoints from Phase 4 (`backend/accounts`). */

import { api } from './client.ts'
import { tokenStore, type TokenPair } from './tokens.ts'

export type Role = 'admin' | 'manager' | 'member'

export interface User {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
  role: Role
  role_display: string
  is_staff: boolean
  is_superuser: boolean
  date_joined: string
}

interface LoginResponse extends TokenPair {
  user: User
}

/** Exchange credentials for a token pair and store it. */
export async function login(username: string, password: string): Promise<User> {
  const data = await api.post<LoginResponse>(
    '/api/auth/login/',
    { username, password },
    { anonymous: true },
  )
  tokenStore.set({ access: data.access, refresh: data.refresh })
  return data.user
}

/** The authenticated user, read from the database rather than the token claims. */
export const fetchMe = () => api.get<User>('/api/auth/me/')

/**
 * Discard the stored tokens.
 *
 * Logout is client-side: the access token stays valid until it expires, which is
 * why ACCESS_TOKEN_LIFETIME is short. Server-side revocation needs simplejwt's
 * blacklist app and is recorded in BACKLOG.md.
 */
export function logout(): void {
  tokenStore.clear()
}

/** Whether a stored session exists. Does not prove the token is still valid. */
export const hasStoredSession = (): boolean => tokenStore.getRefresh() !== null

/** Role ranking, mirroring `ROLE_RANK` in backend/accounts/models.py. */
const ROLE_RANK: Record<Role, number> = { member: 1, manager: 2, admin: 3 }

/**
 * True when `user` holds `role` or a more privileged one.
 *
 * For rendering decisions only — the server re-checks every request.
 */
export function hasRoleAtLeast(user: User | null, role: Role): boolean {
  if (!user) return false
  if (user.is_superuser) return true
  return (ROLE_RANK[user.role] ?? 0) >= ROLE_RANK[role]
}
