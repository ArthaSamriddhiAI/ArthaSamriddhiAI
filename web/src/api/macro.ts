import { useQuery } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/d0/macro/schemas.py.
// Cluster 3 chunk 3.3 surfaces. Chunk 3.4 wires these into the audit-role
// admin UI; this module ships the types + react-query hooks now so
// chunk 3.4's UI work is a thin layer over the typed API.

export interface MacroSnapshot {
  macro_snapshot_id: string

  country_code: string
  snapshot_period: string
  snapshot_date: string

  gdp_growth_pct: number | null
  cpi_inflation_pct: number | null
  wpi_inflation_pct: number | null
  repo_rate_pct: number | null
  reverse_repo_rate_pct: number | null
  bond_yield_10y_pct: number | null
  fx_usd_inr: number | null
  unemployment_rate_pct: number | null

  notes: string | null
  themes: string[]

  source_identifier: string
  source_subkey: string | null
  staging_record_id: string | null
  adapter_run_id: string | null

  created_at: string
  last_modified_at: string
  schema_version: number
}

export interface MacroSnapshotListResponse {
  snapshots: MacroSnapshot[]
  total: number
  limit: number
  offset: number
}

export interface MacroSnapshotFilters {
  country_code?: string
  snapshot_period?: string
  limit?: number
  offset?: number
}

function buildQuery(filters: MacroSnapshotFilters): string {
  const params = new URLSearchParams()
  if (filters.country_code) params.set('country_code', filters.country_code)
  if (filters.snapshot_period)
    params.set('snapshot_period', filters.snapshot_period)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export function useMacroSnapshots(filters: MacroSnapshotFilters = {}) {
  return useQuery<MacroSnapshotListResponse>({
    queryKey: ['macro-snapshots', 'list', filters],
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/admin/macro-snapshots${buildQuery(filters)}`,
      )
      if (!r.ok) {
        throw new Error(`macro-snapshots fetch failed: ${r.status}`)
      }
      return (await r.json()) as MacroSnapshotListResponse
    },
  })
}

export function useMacroSnapshot(macroSnapshotId: string | undefined) {
  return useQuery<MacroSnapshot>({
    queryKey: ['macro-snapshots', 'detail', macroSnapshotId],
    enabled: Boolean(macroSnapshotId),
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/admin/macro-snapshots/${macroSnapshotId}`,
      )
      if (!r.ok) {
        throw new Error(`macro-snapshot fetch failed: ${r.status}`)
      }
      return (await r.json()) as MacroSnapshot
    },
  })
}
