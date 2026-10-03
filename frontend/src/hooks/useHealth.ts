import { useEffect, useState } from 'react'
import { getHealth, type HealthResponse } from '../api/client.ts'

interface HealthState {
  data: HealthResponse | null
  error: Error | null
  loading: boolean
}

/** Fetch `GET /api/health/` once on mount. */
export function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({
    data: null,
    error: null,
    loading: true,
  })

  useEffect(() => {
    const controller = new AbortController()

    getHealth()
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ data, error: null, loading: false })
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            data: null,
            error: error instanceof Error ? error : new Error(String(error)),
            loading: false,
          })
        }
      })

    return () => controller.abort()
  }, [])

  return state
}
