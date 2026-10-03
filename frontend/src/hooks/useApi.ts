import { useCallback, useEffect, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  error: Error | null
  loading: boolean
  reload: () => void
}

/**
 * Run an async loader whenever `deps` change, and expose a reload handle.
 *
 * Two deliberate choices:
 *
 * - **`loading` is derived, not stored.** The settled result carries the key it
 *   was fetched for; anything whose key differs from the current one is by
 *   definition still in flight. Storing it would mean a synchronous setState
 *   inside the effect, which the React Compiler rightly flags as a cascading
 *   render.
 * - **The effect keys on `deps`, not on the loader's identity.** Callers pass an
 *   inline arrow, so its identity changes every render; re-running on that would
 *   loop forever. `deps` is the caller's own declaration of what the request
 *   depends on, which is why it is the dependency list.
 *
 * A result whose key no longer matches is discarded, so a fast filter change
 * cannot let a stale response overwrite a newer one.
 */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [nonce, setNonce] = useState(0)
  const key = `${JSON.stringify(deps)}|${nonce}`

  const [settled, setSettled] = useState<{
    key: string
    data: T | null
    error: Error | null
  } | null>(null)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    let cancelled = false

    loader()
      .then((data) => {
        if (!cancelled) setSettled({ key, data, error: null })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSettled({
            key,
            data: null,
            error: error instanceof Error ? error : new Error(String(error)),
          })
        }
      })

    return () => {
      cancelled = true
    }
    // `loader` is intentionally omitted: callers pass an inline closure whose
    // identity changes every render, and `key` already encodes the `deps` the
    // caller declared the request to depend on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const current = settled?.key === key ? settled : null

  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: current === null,
    reload,
  }
}
