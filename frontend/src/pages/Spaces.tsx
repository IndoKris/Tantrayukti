import { PagePlaceholder } from '../components/PagePlaceholder.tsx'

export default function Spaces() {
  return (
    <PagePlaceholder
      title="Spaces"
      phase="Backend Phase 5 · UI Phase 18"
      description="The organisation → building → floor → room hierarchy, with the devices attached to each space."
      planned={[
        'Tree view of organisations, buildings, floors and rooms',
        'Area (m²) and occupancy per space, used to normalise comparisons',
        'Space-vs-space comparison chart, ranked and normalised per m² and per person',
        'CRUD scoped to the spaces your role can see',
      ]}
    />
  )
}
