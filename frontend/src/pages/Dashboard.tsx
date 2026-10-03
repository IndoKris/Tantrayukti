import { PagePlaceholder } from '../components/PagePlaceholder.tsx'
import { useHealth } from '../hooks/useHealth.ts'

/** Shows the live backend handshake so the API wiring is verifiable in the browser. */
function BackendCard() {
  const { data, error, loading } = useHealth()

  return (
    <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
      <h2 className="text-sm font-semibold">Backend connection</h2>

      {loading && <p className="mt-2 text-sm text-(--surface-muted)">Contacting the API…</p>}

      {error && (
        <div className="mt-2 text-sm">
          <p className="font-medium text-severity-high">Could not reach the API.</p>
          <p className="mt-1 text-(--surface-muted)">
            Start the backend with{' '}
            <code className="rounded bg-(--surface) px-1.5 py-0.5 font-mono text-xs">
              cd backend && uv run python manage.py runserver
            </code>
            , then reload.
          </p>
        </div>
      )}

      {data && (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
          {[
            { label: 'Service', value: data.service },
            { label: 'Version', value: data.version },
            { label: 'Environment', value: data.environment },
            { label: 'Database', value: `${data.database.engine} (${data.database.configured_via})` },
          ].map((row) => (
            <div key={row.label}>
              <dt className="text-xs text-(--surface-muted)">{row.label}</dt>
              <dd className="tabular font-medium">{row.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

export default function Dashboard() {
  return (
    <PagePlaceholder
      title="Dashboard"
      phase="Live monitor: Phase 17"
      description="Real-time power draw, cumulative energy, and the cost and CO₂ those imply, for the spaces you can see."
      planned={[
        'Live wattage chart (W) with a 24 h forecast overlay from the LSTM model',
        'Cumulative energy card in kWh, never mixed with instantaneous kW',
        'Cost and CO₂ cards that name the emission factor and its source',
        'Device online/offline badges driven by last-seen timestamps',
      ]}
    >
      <BackendCard />
    </PagePlaceholder>
  )
}
