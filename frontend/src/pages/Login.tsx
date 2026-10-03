import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../api/client.ts'
import { useAuth } from '../auth/context.ts'

/** Turn a DRF error payload into one line a person can act on. */
function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return 'That username and password do not match an active account.'
    }
    const payload = error.payload
    if (payload && typeof payload === 'object') {
      const detail = (payload as Record<string, unknown>).detail
      if (typeof detail === 'string') return detail
      const first = Object.values(payload as Record<string, unknown>)[0]
      if (Array.isArray(first) && typeof first[0] === 'string') return first[0]
    }
    if (error.status >= 500) return 'The server failed to respond. Is the backend running?'
    return error.message
  }
  // fetch() rejects like this when the API is unreachable.
  return 'Could not reach the API. Start the backend and try again.'
}

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const from = (location.state as { from?: string } | null)?.from ?? '/'

  if (user) {
    return <Navigate to={from} replace />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username, password)
      navigate(from, { replace: true })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setSubmitting(false)
    }
  }

  const fieldClass =
    'w-full rounded-lg border border-(--surface-border) bg-(--surface) px-3 py-2 text-sm text-(--surface-text) placeholder:text-(--surface-muted) focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-eco-500'

  return (
    <div className="flex min-h-svh items-center justify-center bg-(--surface) px-4 py-10 font-sans text-(--surface-text)">
      <div className="w-full max-w-sm">
        <div className="mb-6">
          <p className="text-xl font-semibold tracking-tight">
            Eco<span className="text-eco-600">Track</span>
          </p>
          <p className="mt-1 text-sm text-(--surface-muted)">
            Sign in to see energy, cost and CO&#8322; for your spaces.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="flex flex-col gap-4 rounded-xl border border-(--surface-border) bg-(--surface-raised) p-6"
          noValidate
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="username" className="text-sm font-medium">
              Username
            </label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              required
              autoFocus
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className={fieldClass}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="password" className="text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className={fieldClass}
            />
          </div>

          {error && (
            <p role="alert" className="text-sm font-medium text-severity-high">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="rounded-lg bg-eco-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-eco-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>

          <p className="text-xs text-(--surface-muted)">
            No account yet? Create one with{' '}
            <code className="rounded bg-(--surface) px-1.5 py-0.5 font-mono">
              uv run python manage.py createsuperuser
            </code>{' '}
            in <code className="font-mono">backend/</code>.
          </p>
        </form>
      </div>
    </div>
  )
}
