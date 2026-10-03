import { useHealth } from '../hooks/useHealth.ts'

/**
 * Live backend reachability indicator.
 *
 * Doubles as the end-to-end proof that the API client and the Phase 2 health
 * endpoint talk to each other. It never claims "connected" without a response.
 */
export function ApiStatusBadge() {
  const { data, error, loading } = useHealth()

  const { dot, label, title } = loading
    ? { dot: 'bg-(--surface-muted)', label: 'Checking API', title: 'Contacting the backend' }
    : error
      ? { dot: 'bg-severity-high', label: 'API offline', title: error.message }
      : data?.status === 'ok'
        ? {
            dot: 'bg-eco-500',
            label: `API v${data.version}`,
            title: `${data.environment} · ${data.database.engine} (${data.database.configured_via})`,
          }
        : {
            dot: 'bg-severity-medium',
            label: 'API degraded',
            title: data?.database.error ?? 'The backend reported a degraded state',
          }

  return (
    <span
      title={title}
      className="inline-flex items-center gap-2 rounded-full border border-(--surface-border) bg-(--surface-raised) px-2.5 py-1 text-xs font-medium"
    >
      <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${dot}`} />
      {label}
    </span>
  )
}
