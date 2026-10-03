/** Gamification endpoints (Phase 21). */

import { api } from './client.ts'

export interface GameProfile {
  username: string
  level: number
  verified_xp: number
  verified_kwh_saved: string
  eco_coins: number
  /** From self-reported activity. Never affects rank, levels or badges. */
  unverified_xp: number
  total_xp_including_unverified: number
  xp_into_level: number
  xp_to_next_level: number
  streak_days: number
  longest_streak_days: number
  last_active_on: string | null
}

export interface BadgeRow {
  id: number
  code: string
  name: string
  description: string
  emoji: string
  threshold_verified_kwh: string | null
  threshold_streak_days: number | null
  threshold_verified_claims: number | null
  requires_verified: boolean
}

export interface ChallengeRow {
  id: number
  name: string
  description: string
  target_kwh: string
  reward_xp: number
  reward_coins: number
  starts_on: string
  ends_on: string
  is_active: boolean
  is_open: boolean
  participant_count: number
}

export interface ParticipationRow {
  id: number
  challenge: ChallengeRow
  verified_kwh_saved: string
  progress_percent: string | null
  is_complete: boolean
  completed_at: string | null
  joined_at: string
}

export interface GameProfileResponse {
  profile: GameProfile
  badges: { id: number; badge: BadgeRow; awarded_at: string }[]
  challenges: ParticipationRow[]
  ranking_note: string
}

export const getGameProfile = () => api.get<GameProfileResponse>('/api/game/profile/')

export interface LeaderboardRow {
  rank: number
  username: string
  level: number
  verified_xp: number
  verified_kwh_saved: string
  eco_coins: number
  streak_days: number
  /** Shown so the exclusion is visible rather than mysterious. */
  unverified_xp_excluded: number
}

export interface LeaderboardResponse {
  results: LeaderboardRow[]
  me: {
    username: string
    rank: number | null
    verified_xp: number
    verified_kwh_saved: string
    unverified_xp_excluded: number
    in_top: boolean
  }
  basis: string
}

export const getLeaderboard = (limit = 20) =>
  api.get<LeaderboardResponse>('/api/game/leaderboard/', { params: { limit } })

export const getChallenges = () =>
  api.get<{ count: number; results: ChallengeRow[] }>('/api/game/challenges/', {
    params: { page_size: 50 },
  })

export const joinChallenge = (id: number) =>
  api.post<ParticipationRow>(`/api/game/challenges/${id}/join/`)

export interface SavingClaimRow {
  id: number
  device: number
  device_name: string
  action_taken: string
  baseline_start: string
  baseline_end: string
  claim_start: string
  claim_end: string
  claimed_kwh_saved: string
  baseline_kwh: string | null
  claim_period_kwh: string | null
  measured_kwh_saved: string | null
  claim_accuracy_percent: string | null
  status: 'pending' | 'verified' | 'rejected' | 'unverifiable'
  status_display: string
  is_verified: boolean
  verification_note: string
  verified_at: string | null
}

export const getSavingClaims = () =>
  api.get<{ count: number; results: SavingClaimRow[] }>('/api/game/claims/', {
    params: { page_size: 50 },
  })

export const createSavingClaim = (body: {
  device: number
  action_taken: string
  baseline_start: string
  baseline_end: string
  claim_start: string
  claim_end: string
  claimed_kwh_saved: string
}) => api.post<SavingClaimRow>('/api/game/claims/', body)

export const verifySavingClaim = (id: number) =>
  api.post<{ claim: SavingClaimRow; profile: GameProfile }>(
    `/api/game/claims/${id}/verify/`,
  )

export const previewSavingClaim = (id: number) =>
  api.post<{ claim: SavingClaimRow; note: string }>(`/api/game/claims/${id}/preview/`)
