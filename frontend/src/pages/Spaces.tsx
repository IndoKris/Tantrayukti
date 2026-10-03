import { useMemo, useState } from 'react'

import { compareSpaces, getSpaceTree, type TreeOrganisation } from '../api/insights.ts'
import { AsyncBoundary } from '../components/AsyncBoundary.tsx'
import { ChartFrame, RankedBarChart } from '../components/charts.tsx'
import { SERIES } from '../components/chartTokens.ts'
import { useApi } from '../hooks/useApi.ts'

type Scope = { kind: string; id: number; label: string }

/** Organisation → building → floor → room, from the single prefetched tree call. */
function SpaceTree({ onSelect, selected }: { onSelect: (scope: Scope) => void; selected: Scope | null }) {
  const { data, error, loading } = useApi(() => getSpaceTree(), [])

  const isSelected = (kind: string, id: number) =>
    selected?.kind === kind && selected?.id === id

  const rowClass = (kind: string, id: number) =>
    `w-full rounded-lg px-2 py-1 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-eco-500 ${
      isSelected(kind, id)
        ? 'bg-eco-600/10 font-medium text-(--surface-text)'
        : 'text-(--surface-muted) hover:text-(--surface-text)'
    }`

  return (
    <AsyncBoundary loading={loading} error={error} label="spaces">
      {!data?.length ? (
        <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5 text-sm text-(--surface-muted)">
          No spaces yet. Seed the sample office and home:
          <pre className="mt-2 overflow-x-auto rounded-lg bg-(--surface) p-3 font-mono text-xs">
            cd backend &amp;&amp; uv run python manage.py seed_spaces
          </pre>
        </div>
      ) : (
        <nav
          aria-label="Spaces"
          className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-4"
        >
          <ul className="flex flex-col gap-1">
            {data.map((org: TreeOrganisation) => (
              <li key={org.id}>
                <button
                  type="button"
                  onClick={() => onSelect({ kind: 'organisation', id: org.id, label: org.name })}
                  className={rowClass('organisation', org.id)}
                >
                  {org.name}{' '}
                  <span className="tabular text-xs text-(--surface-muted)">
                    {org.total_area_sqm ?? '—'} m² · {org.total_occupancy} people
                  </span>
                </button>

                <ul className="mt-0.5 flex flex-col gap-0.5 border-l border-(--surface-border) pl-3">
                  {org.buildings.map((building) => (
                    <li key={building.id}>
                      <button
                        type="button"
                        onClick={() =>
                          onSelect({ kind: 'building', id: building.id, label: building.name })
                        }
                        className={rowClass('building', building.id)}
                      >
                        {building.name}{' '}
                        <span className="tabular text-xs text-(--surface-muted)">
                          {building.total_area_sqm ?? '—'} m²
                        </span>
                      </button>

                      <ul className="mt-0.5 flex flex-col gap-0.5 border-l border-(--surface-border) pl-3">
                        {building.floors.map((floor) => (
                          <li key={floor.id}>
                            <button
                              type="button"
                              onClick={() =>
                                onSelect({ kind: 'floor', id: floor.id, label: floor.name })
                              }
                              className={rowClass('floor', floor.id)}
                            >
                              {floor.name}{' '}
                              <span className="tabular text-xs text-(--surface-muted)">
                                L{floor.level} · {floor.rooms.length} room(s)
                              </span>
                            </button>

                            <ul className="mt-0.5 flex flex-col gap-0.5 border-l border-(--surface-border) pl-3">
                              {floor.rooms.map((room) => (
                                <li
                                  key={room.id}
                                  className="px-2 py-0.5 text-sm text-(--surface-muted)"
                                >
                                  {room.name}{' '}
                                  <span className="tabular text-xs">
                                    {room.area_sqm ?? '—'} m² ·{' '}
                                    {room.occupancy ?? '—'} people
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </AsyncBoundary>
  )
}

const NORMALISATIONS = [
  { value: 'area', label: 'per m²', unit: 'kWh per m²', key: 'kwh_per_sqm' },
  { value: 'occupancy', label: 'per person', unit: 'kWh per person', key: 'kwh_per_person' },
  { value: 'none', label: 'raw total', unit: 'kWh', key: 'energy_kwh' },
] as const

function SpaceComparison({ scope }: { scope: Scope | null }) {
  const [normaliseBy, setNormaliseBy] = useState<'area' | 'occupancy' | 'none'>('area')
  const option = NORMALISATIONS.find((item) => item.value === normaliseBy)!

  const { data, error, loading } = useApi(
    () =>
      scope === null
        ? Promise.resolve(null)
        : compareSpaces({
            space: `${scope.kind}:${scope.id}`,
            normalise_by: normaliseBy,
            period: 'day',
            from: new Date(Date.now() - 7 * 86400_000).toISOString(),
            to: new Date().toISOString(),
          }),
    [scope?.kind, scope?.id, normaliseBy],
  )

  const rows = useMemo(
    () =>
      (data?.results ?? []).map((row) => ({
        name: row.name,
        value: Number(row[option.key] ?? 0),
        energy_kwh: Number(row.energy_kwh),
        area_sqm: row.area_sqm,
      })),
    [data, option.key],
  )

  if (scope === null) {
    return (
      <p className="rounded-xl border border-dashed border-(--surface-border) bg-(--surface-raised) p-5 text-sm text-(--surface-muted)">
        Pick an organisation, building or floor on the left to compare the spaces inside it.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Filters sit in one row above the chart. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-(--surface-muted)">Normalise:</span>
        {NORMALISATIONS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => setNormaliseBy(item.value)}
            aria-pressed={normaliseBy === item.value}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500 ${
              normaliseBy === item.value
                ? 'border-eco-600 bg-eco-600/10 text-(--surface-text)'
                : 'border-(--surface-border) text-(--surface-muted) hover:text-(--surface-text)'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <AsyncBoundary loading={loading} error={error} label="comparison">
        <ChartFrame
          title={`${scope.label}: ${data?.compared_level ?? 'space'}s ranked ${option.label}`}
          unit={option.unit}
          series={[{ key: 'value', label: option.unit, color: SERIES.comparison }]}
          rows={rows}
          xKey="name"
          emptyMessage="No readings for these spaces in the last 7 days."
          footnote={
            <>
              {data?.notes.map((note) => (
                <span key={note} className="block">
                  {note}
                </span>
              ))}
              {data && data.excluded.length > 0 && (
                <span className="mt-1 block text-severity-medium">
                  Excluded: {data.excluded.map((row) => row.name).join(', ')} — no{' '}
                  {data.normalise_by} recorded, so ranking them here would be meaningless.
                </span>
              )}
            </>
          }
        >
          <RankedBarChart
            rows={rows}
            labelKey="name"
            valueKey="value"
            valueLabel={option.unit}
            color={SERIES.comparison}
          />
        </ChartFrame>
      </AsyncBoundary>
    </div>
  )
}

export default function Spaces() {
  const [scope, setScope] = useState<Scope | null>(null)

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Spaces</h1>
        <p className="mt-1 max-w-prose text-sm text-(--surface-muted)">
          The space hierarchy, and energy compared between sibling spaces. Comparisons are
          normalised by area or occupancy, so a large space is not flagged merely for being
          large.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,22rem)_1fr]">
        <SpaceTree onSelect={setScope} selected={scope} />
        <SpaceComparison scope={scope} />
      </div>
    </section>
  )
}
