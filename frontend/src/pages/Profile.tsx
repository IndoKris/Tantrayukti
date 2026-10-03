import { PagePlaceholder } from '../components/PagePlaceholder.tsx'

export default function Profile() {
  return (
    <PagePlaceholder
      title="Profile"
      phase="Backend Phase 4 · Gamification Phase 21"
      description="Your account and role, plus the progress you have earned from verified savings."
      planned={[
        'Account details and role (admin, manager or member)',
        'XP, level, streak and EcoCoins',
        'Badges and challenges, with a leaderboard',
        'Proof of saving: claimed reductions checked against telemetry, unverified entries excluded from ranking',
      ]}
    />
  )
}
