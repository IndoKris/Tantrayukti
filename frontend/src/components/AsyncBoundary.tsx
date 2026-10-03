import type { ReactNode } from 'react'

import { ApiError } from '../api/client.ts'

/**
 * Loading and error presentation shared by every page.
 *
 * A 409 from this backend means "the thing you asked for is not ready yet" and
 * carries an actionable `how_to_fix`, so it is shown as guidance rather than as
 * a failure. That matters because several endpoints legitimately return 409
 * before the simulator or the training step has been run.
 */
export function AsyncBoundary({
  loading,
  error,
  children,
  label,
}: {
  loading: boolean
  error: Error | null
  children: ReactNode
  label: string
}) {
  if (loading) {
    return (
      <p className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5 text-sm text-(--surface-muted)">
        Loading {label}…
      </p>
    )
  }

  if (error) {
    const payload = error instanceof ApiError ? (error.payload as Record<string, unknown>) : null
    const detail = typeof payload?.detail === 'string' ? payload.detail : error.message
    const howToFix = typeof payload?.how_to_fix === 'string' ? payload.how_to_fix : null
    const notReady = error instanceof ApiError && error.status === 409

    return (
      <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
        <p className={`text-sm font-medium ${notReady ? 'text-severity-medium' : 'text-severity-high'}`}>
          {notReady ? 'Not ready yet' : `Could not load ${label}`}
        </p>
        <p className="mt-1 text-sm text-(--surface-muted)">{detail}</p>
        {howToFix && (
          <pre className="mt-3 overflow-x-auto rounded-lg bg-(--surface) p-3 font-mono text-xs">
            {howToFix}
          </pre>
        )}
      </div>
    )
  }

  return <>{children}</>
}
