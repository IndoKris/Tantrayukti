import { PagePlaceholder } from '../components/PagePlaceholder.tsx'

export default function Community() {
  return (
    <PagePlaceholder
      title="Community"
      phase="Phase 22"
      description="How your usage compares with the wider area, and satellite-derived air quality for nearby cities."
      planned={[
        'Leaflet heatmap with coordinates rounded to city level for privacy',
        'NO₂ for 20 cities, shown in column units (mol/m²) — not surface ppb',
        'Hotspot detection using a validated Isolation Forest score threshold',
        'CO₂ trend panel with its prediction interval',
      ]}
    />
  )
}
