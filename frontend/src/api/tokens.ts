/**
 * JWT storage.
 *
 * Tokens live in `localStorage` so a reload keeps you signed in. That is
 * readable by any script on the origin, which is the accepted trade-off for a
 * dashboard demo; an httpOnly refresh cookie would be the hardening step and is
 * recorded in BACKLOG.md. Every access is guarded because storage throws in
 * private windows and when site data is blocked.
 */

const ACCESS_KEY = 'ecotrack.access'
const REFRESH_KEY = 'ecotrack.refresh'

export interface TokenPair {
  access: string
  refresh: string
}

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, value)
    }
  } catch {
    // Non-persistent session: tokens stay in memory for this page only.
  }
}

export const tokenStore = {
  getAccess: () => read(ACCESS_KEY),
  getRefresh: () => read(REFRESH_KEY),

  set({ access, refresh }: TokenPair): void {
    write(ACCESS_KEY, access)
    write(REFRESH_KEY, refresh)
  },

  /** Replace only the access token, after a refresh that did not rotate. */
  setAccess(access: string): void {
    write(ACCESS_KEY, access)
  },

  clear(): void {
    write(ACCESS_KEY, null)
    write(REFRESH_KEY, null)
  },
}
