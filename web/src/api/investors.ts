import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/investors/schemas.py InvestorRead.
export interface Investor {
  investor_id: string
  name: string
  email: string
  phone: string
  pan: string
  age: number
  household_id: string
  advisor_id: string
  risk_appetite: 'aggressive' | 'moderate' | 'conservative'
  time_horizon: 'under_3_years' | '3_to_5_years' | 'over_5_years'
  kyc_status: string
  kyc_verified_at: string | null
  kyc_provider: string | null
  life_stage: 'accumulation' | 'transition' | 'distribution' | 'legacy' | null
  life_stage_confidence: 'high' | 'medium' | 'low' | null
  liquidity_tier: 'essential' | 'secondary' | 'deep' | null
  liquidity_tier_range: string | null
  enriched_at: string | null
  enrichment_version: string | null
  created_at: string
  created_by: string
  created_via: 'form' | 'conversational' | 'api'
  duplicate_pan_acknowledged: boolean
  last_modified_at: string
  last_modified_by: string
  schema_version: number
}

export interface Household {
  household_id: string
  name: string
  created_by: string
  created_at: string
}

export interface InvestorCreatePayload {
  name: string
  email: string
  phone: string
  pan: string
  age: number
  household_id?: string
  household_name?: string
  advisor_id?: string
  risk_appetite: 'aggressive' | 'moderate' | 'conservative'
  time_horizon: 'under_3_years' | '3_to_5_years' | 'over_5_years'
  duplicate_pan_acknowledged?: boolean
}

// Backend's RFC 7807 problem detail body when PAN duplicates and the
// advisor hasn't acknowledged. The form catches this and renders the
// warn-and-proceed dialog.
export interface DuplicatePanProblem {
  type?: string
  title: string
  status: 409
  detail?: string
  duplicate: {
    duplicate_of_investor_id: string
    duplicate_of_name: string
    duplicate_of_created_at: string
    pan: string
  }
}

export class InvestorCreateError extends Error {
  readonly status: number
  readonly problem?: DuplicatePanProblem | Record<string, unknown>

  constructor(
    message: string,
    status: number,
    problem?: DuplicatePanProblem | Record<string, unknown>,
  ) {
    super(message)
    this.name = 'InvestorCreateError'
    this.status = status
    this.problem = problem
  }
}

// ---- queries ----

export function useInvestorsList() {
  return useQuery<Investor[]>({
    queryKey: ['investors'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/investors')
      if (!r.ok) throw new Error(`investors list failed: ${r.status}`)
      const body = (await r.json()) as { investors: Investor[] }
      return body.investors
    },
  })
}

export function useInvestor(investorId: string | undefined) {
  return useQuery<Investor>({
    queryKey: ['investors', investorId],
    enabled: Boolean(investorId),
    queryFn: async () => {
      const r = await apiFetch(`/api/v2/investors/${investorId}`)
      if (!r.ok) throw new Error(`investor fetch failed: ${r.status}`)
      return (await r.json()) as Investor
    },
  })
}

export function useHouseholdsList() {
  return useQuery<Household[]>({
    queryKey: ['households'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/households')
      if (!r.ok) throw new Error(`households list failed: ${r.status}`)
      const body = (await r.json()) as { households: Household[] }
      return body.households
    },
  })
}

// ---- mutations ----

export function useCreateInvestor() {
  const qc = useQueryClient()
  return useMutation<Investor, InvestorCreateError, InvestorCreatePayload>({
    mutationFn: async (payload) => {
      const r = await apiFetch('/api/v2/investors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (r.status === 409) {
        const problem = (await r.json()) as DuplicatePanProblem
        throw new InvestorCreateError('Duplicate PAN', 409, problem)
      }
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new InvestorCreateError(
          (body as { detail?: string }).detail ?? `Create failed (${r.status})`,
          r.status,
          body as Record<string, unknown>,
        )
      }
      return (await r.json()) as Investor
    },
    onSuccess: () => {
      // List + households change after a create — invalidate so consumers refetch.
      void qc.invalidateQueries({ queryKey: ['investors'] })
      void qc.invalidateQueries({ queryKey: ['households'] })
    },
  })
}
