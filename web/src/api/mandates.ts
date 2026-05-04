import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/m1/schemas.py.

export type CreatedVia = 'form' | 'conversational' | 'api' | 'pdf'
export type MandateVersionStatus =
  | 'draft'
  | 'pending_approval'
  | 'active'
  | 'archived'
  | 'rejected'

export interface MandateVersion {
  version_id: string
  mandate_id: string
  version_number: number
  status: MandateVersionStatus

  equity_min_pct: number
  equity_max_pct: number
  debt_min_pct: number
  debt_max_pct: number
  alternatives_min_pct: number
  alternatives_max_pct: number
  single_position_max_pct: number
  liquidity_floor_pct: number
  sector_max_pct: number
  prohibited_instruments: string[]

  created_at: string
  created_by: string
  created_via: CreatedVia
  parent_version_id: string | null

  proposed_at: string | null
  proposed_by: string | null
  approved_at: string | null
  approved_by: string | null
  rejected_at: string | null
  rejected_by: string | null
  rejection_reason: string | null
  approval_comments: string | null
  changes_requested_at: string | null
  changes_requested_by: string | null
  changes_requested_comments: string | null

  activated_at: string | null
  archived_at: string | null
}

export interface Mandate {
  mandate_id: string
  investor_id: string
  active_version_id: string | null
  active_version: MandateVersion | null
  created_at: string
  created_by: string
  schema_version: number
}

export interface SoftWarning {
  field: string
  code: string
  message: string
}

export interface MandateDefaults {
  equity_min_pct: number
  equity_max_pct: number
  debt_min_pct: number
  debt_max_pct: number
  alternatives_min_pct: number
  alternatives_max_pct: number
  single_position_max_pct: number
  liquidity_floor_pct: number
  sector_max_pct: number
  prohibited_instruments: string[]
  sources: Record<string, string>
  risk_appetite: string | null
  liquidity_tier: string | null
}

export interface MandateCreatePayload {
  equity_min_pct: number
  equity_max_pct: number
  debt_min_pct: number
  debt_max_pct: number
  alternatives_min_pct: number
  alternatives_max_pct: number
  single_position_max_pct: number
  liquidity_floor_pct: number
  sector_max_pct: number
  prohibited_instruments: string[]
}

export interface MandateCreateResponse {
  mandate: Mandate
  warnings: SoftWarning[]
}

// 400 from POST /mandate when hard validation fails.
export interface MandateValidationProblem {
  type?: string
  title: string
  status: 400
  detail?: string
  failures: Array<{ field: string; code: string; message: string }>
}

// 409 from POST /mandate when a mandate already exists.
export interface MandateExistsProblem {
  type?: string
  title: string
  status: 409
  detail?: string
  mandate_id: string
  investor_id: string
}

export class MandateError extends Error {
  readonly status: number
  readonly problem?: MandateValidationProblem | MandateExistsProblem | Record<string, unknown>

  constructor(
    message: string,
    status: number,
    problem?: MandateValidationProblem | MandateExistsProblem | Record<string, unknown>,
  ) {
    super(message)
    this.name = 'MandateError'
    this.status = status
    this.problem = problem
  }
}

// ---- queries ----

export function useMandateDefaults(investorId: string | undefined) {
  return useQuery<MandateDefaults>({
    queryKey: ['mandate', 'defaults', investorId],
    enabled: Boolean(investorId),
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/investors/${investorId}/mandate/defaults`,
      )
      if (!r.ok) throw new Error(`mandate defaults fetch failed: ${r.status}`)
      return (await r.json()) as MandateDefaults
    },
  })
}

export function useActiveMandate(investorId: string | undefined) {
  return useQuery<Mandate | null>({
    queryKey: ['mandate', 'active', investorId],
    enabled: Boolean(investorId),
    queryFn: async () => {
      const r = await apiFetch(`/api/v2/investors/${investorId}/mandate`)
      if (r.status === 404) return null
      if (!r.ok) throw new Error(`mandate fetch failed: ${r.status}`)
      return (await r.json()) as Mandate
    },
  })
}

export function useMandateVersions(investorId: string | undefined) {
  return useQuery<MandateVersion[]>({
    queryKey: ['mandate', 'versions', investorId],
    enabled: Boolean(investorId),
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/investors/${investorId}/mandate/versions`,
      )
      if (!r.ok) throw new Error(`mandate versions fetch failed: ${r.status}`)
      const body = (await r.json()) as { versions: MandateVersion[] }
      return body.versions
    },
  })
}

// ---- mutations ----

export function useCreateMandate(investorId: string) {
  const qc = useQueryClient()
  return useMutation<MandateCreateResponse, MandateError, MandateCreatePayload>({
    mutationFn: async (payload) => {
      const r = await apiFetch(`/api/v2/investors/${investorId}/mandate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as Record<string, unknown>
        const detail = (body.detail as string | undefined) ?? `Create failed (${r.status})`
        throw new MandateError(detail, r.status, body as never)
      }
      return (await r.json()) as MandateCreateResponse
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['mandate'] })
    },
  })
}
