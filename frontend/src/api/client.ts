/**
 * EcoTrack API client.
 *
 * Base URL resolution:
 *   1. `VITE_API_BASE_URL` when set (deployed builds, or pointing at a remote API).
 *   2. Otherwise the empty string, so requests go to a same-origin `/api/...` path
 *      and are forwarded by the Vite dev proxy in vite.config.ts.
 *
 * Authentication (Phase 4) is handled here rather than in components: the access
 * token is attached automatically, and a 401 triggers one refresh-and-retry before
 * the error is surfaced.
 */

import { tokenStore } from './tokens.ts'

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''

/** Normalised API base URL, never with a trailing slash. */
export const API_BASE_URL = rawBaseUrl.replace(/\/+$/, '')

/** Error carrying the HTTP status and the parsed response body, when there was one. */
export class ApiError extends Error {
  readonly status: number
  readonly payload: unknown

  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  /** Query-string parameters; `undefined` and `null` values are dropped. */
  params?: Record<string, string | number | boolean | null | undefined>
  /** JSON request body. Serialised automatically with the right Content-Type. */
  json?: unknown
  /** Send without the Authorization header (login, refresh, health). */
  anonymous?: boolean
  /** Internal: set while replaying a request after a token refresh. */
  _retried?: boolean
}

/** Called when refreshing fails, so the app can send the user back to /login. */
type SessionExpiredHandler = () => void

let onSessionExpired: SessionExpiredHandler = () => {}

export function setSessionExpiredHandler(handler: SessionExpiredHandler): void {
  onSessionExpired = handler
}

/**
 * Exchange the stored refresh token for a new access token.
 *
 * Concurrent 401s share one in-flight refresh, so a page with several queries
 * does not fire several refreshes and rotate the token out from under itself.
 */
let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refresh = tokenStore.getRefresh()
  if (!refresh) return null

  refreshInFlight ??= (async () => {
    try {
      const data = await request<{ access: string; refresh?: string }>('/api/auth/refresh/', {
        method: 'POST',
        json: { refresh },
        anonymous: true,
      })
      // ROTATE_REFRESH_TOKENS is on in the backend, so store the new one when sent.
      if (data.refresh) {
        tokenStore.set({ access: data.access, refresh: data.refresh })
      } else {
        tokenStore.setAccess(data.access)
      }
      return data.access
    } catch {
      tokenStore.clear()
      onSessionExpired()
      return null
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  const normalisedPath = path.startsWith('/') ? path : `/${path}`
  const search = new URLSearchParams()

  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) {
      search.append(key, String(value))
    }
  }

  const query = search.toString()
  return `${API_BASE_URL}${normalisedPath}${query ? `?${query}` : ''}`
}

/**
 * Perform an API request and parse the JSON response.
 *
 * Throws `ApiError` on any non-2xx status, with the decoded body attached so
 * callers can surface DRF's field-level validation errors.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, json, headers, anonymous, _retried, ...init } = options
  const access = anonymous ? null : tokenStore.getAccess()

  const response = await fetch(buildUrl(path, params), {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(access ? { Authorization: `Bearer ${access}` } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : undefined,
  })

  // Expired access token: refresh once, then replay the original request.
  if (response.status === 401 && !anonymous && !_retried && tokenStore.getRefresh()) {
    const renewed = await refreshAccessToken()
    if (renewed) {
      return request<T>(path, { ...options, _retried: true })
    }
  }

  const contentType = response.headers.get('content-type') ?? ''
  const payload: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => null)

  if (!response.ok) {
    throw new ApiError(
      `${init.method ?? 'GET'} ${path} failed with ${response.status}`,
      response.status,
      payload,
    )
  }

  return payload as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', json }),
  patch: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', json }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
}

// --- Endpoints -----------------------------------------------------------------

/** Response shape of `GET /api/health/` as built in Phase 2. */
export interface HealthResponse {
  status: 'ok' | 'degraded'
  service: string
  version: string
  environment: string
  debug: boolean
  time: string
  database: {
    engine: string
    configured_via: 'DATABASE_URL' | 'sqlite-fallback'
    reachable: boolean
    error?: string
  }
}

export const getHealth = () => api.get<HealthResponse>('/api/health/', { anonymous: true })
