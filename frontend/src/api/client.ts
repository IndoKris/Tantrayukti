/**
 * EcoTrack API client.
 *
 * Base URL resolution:
 *   1. `VITE_API_BASE_URL` when set (deployed builds, or pointing at a remote API).
 *   2. Otherwise the empty string, so requests go to a same-origin `/api/...` path
 *      and are forwarded by the Vite dev proxy in vite.config.ts.
 *
 * Later phases add the JWT token handling from Phase 4 inside `request()`, so no
 * component ever has to know how auth is attached.
 */

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
  const { params, json, headers, ...init } = options

  const response = await fetch(buildUrl(path, params), {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : undefined,
  })

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

export const getHealth = () => api.get<HealthResponse>('/api/health/')
