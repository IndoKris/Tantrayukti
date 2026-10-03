import { PagePlaceholder } from '../components/PagePlaceholder.tsx'

export default function Reports() {
  return (
    <PagePlaceholder
      title="Reports"
      phase="Backend Phases 9, 20 · UI Phase 18"
      description="Bill estimates and projections, period-over-period comparisons, and your logged activity footprint."
      planned={[
        'Bill estimate and month projection from slab and time-of-day tariffs',
        'Period-vs-period comparison: day, week, month, same weekday last week',
        'Activity log across transport, home energy, diet, shopping and waste',
        'Budget vs usage, top emitters, and CSV export',
      ]}
    />
  )
}
