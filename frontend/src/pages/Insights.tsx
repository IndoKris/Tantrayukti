import { PagePlaceholder } from '../components/PagePlaceholder.tsx'

export default function Insights() {
  return (
    <PagePlaceholder
      title="Insights"
      phase="Backend Phases 13–15 · UI Phase 19"
      description="Abnormal usage detected automatically, the likely cause with its evidence, and what to do about it."
      planned={[
        'Anomaly feed with severity, and acknowledge/resolve states',
        'Ranked cause explanation showing expected vs actual and the evidence behind it',
        'Recommendations with kWh, ₹ and kg CO₂ saved per month, plus the formula used',
        'Demo mode: inject a fault and watch detection → cause → recommendation',
        'ML metrics read from backend/ml/artifacts/metrics.json — never hard-coded',
      ]}
    />
  )
}
