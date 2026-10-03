import { useState } from 'react'

import {
  getChallenges,
  getGameProfile,
  getLeaderboard,
  joinChallenge,
  type LeaderboardRow,
} from '../api/game.ts'
import { useAuth } from '../auth/context.ts'
import { AsyncBoundary } from '../components/AsyncBoundary.tsx'
import { StatTile } from '../components/charts.tsx'
import { useApi } from '../hooks/useApi.ts'

/**
 * Profile, badges, challenges and the leaderboard.
 *
 * The verified/unverified split is shown prominently rather than buried: a
 * player who logs a lot of activity and never climbs the leaderboard deserves to
 * see why. Levels, badges and challenge progress all come from verified savings
 * only.
 */

function LevelBar({ into, toNext }: { into: number; toNext: number }) {
  const total = into + toNext
  const percent = total > 0 ? Math.round((into / total) * 100) : 0

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-(--surface-muted)">Progress to next level</span>
        <span className="tabular font-medium">
          {into} / {total} XP
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Progress to next level"
        className="h-2 overflow-hidden rounded-full bg-(--surface)"
      >
        <div className="h-full rounded-full bg-eco-600" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

function Leaderboard() {
  const { data, error, loading } = useApi(() => getLeaderboard(), [])
  const { user } = useAuth()

  return (
    <AsyncBoundary loading={loading} error={error} label="leaderboard">
      {data && (
        <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
          <h2 className="text-sm font-semibold">Leaderboard</h2>
          <p className="mt-1 text-xs text-(--surface-muted)">{data.basis}</p>

          {data.results.length === 0 ? (
            <p className="mt-3 text-sm text-(--surface-muted)">
              Nobody has a telemetry-confirmed saving yet. Submit a claim below to be first.
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs tabular">
                <thead>
                  <tr className="border-b border-(--surface-border)">
                    <th className="py-1.5 pr-3 font-medium">#</th>
                    <th className="py-1.5 pr-3 font-medium">Player</th>
                    <th className="py-1.5 pr-3 font-medium">Level</th>
                    <th className="py-1.5 pr-3 font-medium">Verified XP</th>
                    <th className="py-1.5 pr-3 font-medium">kWh saved</th>
                    <th className="py-1.5 pr-3 font-medium">Streak</th>
                    <th className="py-1.5 font-medium text-(--surface-muted)">
                      Unverified (excluded)
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((row: LeaderboardRow) => (
                    <tr
                      key={row.username}
                      className={`border-b border-(--surface-border)/50 ${
                        row.username === user?.username ? 'bg-eco-600/5 font-medium' : ''
                      }`}
                    >
                      <td className="py-1 pr-3 text-(--surface-muted)">{row.rank}</td>
                      <td className="py-1 pr-3">{row.username}</td>
                      <td className="py-1 pr-3">{row.level}</td>
                      <td className="py-1 pr-3">{row.verified_xp}</td>
                      <td className="py-1 pr-3">{Number(row.verified_kwh_saved).toFixed(2)}</td>
                      <td className="py-1 pr-3">{row.streak_days}d</td>
                      <td className="py-1 text-(--surface-muted)">
                        {row.unverified_xp_excluded}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!data.me.in_top && (
            <p className="mt-3 text-xs text-(--surface-muted)">
              You are not in the top {data.results.length}: {data.me.verified_xp} verified XP
              from {Number(data.me.verified_kwh_saved).toFixed(2)} confirmed kWh.
              {data.me.unverified_xp_excluded > 0 && (
                <>
                  {' '}
                  Your {data.me.unverified_xp_excluded} unverified XP from logged activity does
                  not count here.
                </>
              )}
            </p>
          )}
        </div>
      )}
    </AsyncBoundary>
  )
}

export default function Profile() {
  const [nonce, setNonce] = useState(0)
  const { data, error, loading } = useApi(() => getGameProfile(), [nonce])
  const { user } = useAuth()
  const [busy, setBusy] = useState<number | null>(null)

  async function join(id: number) {
    setBusy(id)
    try {
      await joinChallenge(id)
      setNonce((value) => value + 1)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
        <p className="mt-1 max-w-prose text-sm text-(--surface-muted)">
          {user ? `${user.username} · ${user.role_display}` : 'Your account'}. Progress comes
          from reductions a meter confirmed; self-reported activity is tracked separately and
          never affects your rank.
        </p>
      </div>

      <AsyncBoundary loading={loading} error={error} label="profile">
        {data && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                label="Level"
                value={data.profile.level}
                unit=""
                source="From verified XP only"
              />
              <StatTile
                label="Verified savings"
                value={Number(data.profile.verified_kwh_saved).toFixed(2)}
                unit="kWh"
                tone="good"
                source={`${data.profile.verified_xp} XP · counts towards your rank`}
              />
              <StatTile
                label="EcoCoins"
                value={data.profile.eco_coins}
                unit=""
                source="Earned from confirmed savings"
              />
              <StatTile
                label="Streak"
                value={data.profile.streak_days}
                unit="days"
                source={`Longest ${data.profile.longest_streak_days} days`}
              />
            </div>

            <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
              <LevelBar
                into={data.profile.xp_into_level}
                toNext={data.profile.xp_to_next_level}
              />
              {data.profile.unverified_xp > 0 && (
                <p className="mt-3 rounded-lg border border-severity-medium/40 bg-severity-medium/10 p-2.5 text-xs">
                  You also hold <strong>{data.profile.unverified_xp} unverified XP</strong> from
                  self-reported activity. It is shown on your profile but excluded from levels,
                  badges, challenges and the leaderboard — a logged journey is not evidence the
                  way a metered kWh is.
                </p>
              )}
            </div>

            <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
              <h2 className="text-sm font-semibold">Badges</h2>
              {data.badges.length === 0 ? (
                <p className="mt-2 text-sm text-(--surface-muted)">
                  None yet. Every badge needs a telemetry-confirmed saving.
                </p>
              ) : (
                <ul className="mt-3 flex flex-wrap gap-2">
                  {data.badges.map((award) => (
                    <li
                      key={award.id}
                      title={award.badge.description}
                      className="flex items-center gap-2 rounded-lg border border-(--surface-border) px-2.5 py-1.5 text-xs"
                    >
                      <span aria-hidden="true">{award.badge.emoji}</span>
                      <span className="font-medium">{award.badge.name}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
              <h2 className="text-sm font-semibold">Challenges</h2>
              {data.challenges.length === 0 ? (
                <p className="mt-2 text-sm text-(--surface-muted)">
                  Not taking part in any challenge yet.
                </p>
              ) : (
                <ul className="mt-3 flex flex-col gap-3">
                  {data.challenges.map((entry) => (
                    <li key={entry.id} className="rounded-lg border border-(--surface-border) p-3">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <p className="text-sm font-medium">{entry.challenge.name}</p>
                        <span className="tabular text-xs text-(--surface-muted)">
                          {Number(entry.verified_kwh_saved).toFixed(2)} /{' '}
                          {Number(entry.challenge.target_kwh).toFixed(0)} kWh verified
                          {entry.is_complete && ' · complete'}
                        </span>
                      </div>
                      <div
                        role="progressbar"
                        aria-valuenow={Math.min(100, Number(entry.progress_percent ?? 0))}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label={`${entry.challenge.name} progress`}
                        className="mt-2 h-1.5 overflow-hidden rounded-full bg-(--surface)"
                      >
                        <div
                          className={`h-full rounded-full ${
                            entry.is_complete ? 'bg-eco-500' : 'bg-eco-600'
                          }`}
                          style={{
                            width: `${Math.min(100, Number(entry.progress_percent ?? 0))}%`,
                          }}
                        />
                      </div>
                      {entry.challenge.description && (
                        <p className="mt-2 text-xs text-(--surface-muted)">
                          {entry.challenge.description}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <OpenChallenges onJoin={join} busy={busy} />
            </div>

            <Leaderboard />
          </>
        )}
      </AsyncBoundary>
    </section>
  )
}

function OpenChallenges({
  onJoin,
  busy,
}: {
  onJoin: (id: number) => void
  busy: number | null
}) {
  const { data } = useApi(() => getChallenges(), [])
  const joinable = (data?.results ?? []).filter((challenge) => challenge.is_open)

  if (joinable.length === 0) return null

  return (
    <div className="mt-4 border-t border-(--surface-border) pt-3">
      <h3 className="text-xs font-semibold tracking-wide uppercase text-(--surface-muted)">
        Open challenges
      </h3>
      <ul className="mt-2 flex flex-col gap-2">
        {joinable.map((challenge) => (
          <li key={challenge.id} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm">
              {challenge.name}{' '}
              <span className="tabular text-xs text-(--surface-muted)">
                target {Number(challenge.target_kwh).toFixed(0)} verified kWh ·{' '}
                {challenge.participant_count} taking part
              </span>
            </span>
            <button
              type="button"
              onClick={() => onJoin(challenge.id)}
              disabled={busy === challenge.id}
              className="rounded-lg border border-(--surface-border) px-2.5 py-1 text-xs font-medium disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
            >
              {busy === challenge.id ? 'Joining…' : 'Join'}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
