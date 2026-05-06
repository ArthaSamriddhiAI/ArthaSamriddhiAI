import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/cases/seed_router.py.
// CIO-only seed framework surface (FR Entry 19.0). Cluster 5 chunk 5.6.

export interface SeedStatus {
  is_loaded: boolean
  counts: {
    investors: number
    households: number
    mandates: number
    cases: number
  }
}

export interface SeedLoadResult {
  households: number
  investors: number
  mandates: number
  cases: number
}

export interface SeedResetResult {
  cases_deleted: number
  mandates_deleted: number
  mandate_versions_deleted: number
  investors_deleted: number
  households_deleted: number
  snapshots_deleted: number
  stage_rows_deleted: number
}

export function useSeedStatus() {
  return useQuery<SeedStatus>({
    queryKey: ['seed', 'status'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/admin/seed/status')
      if (!r.ok) throw new Error(`seed status failed: ${r.status}`)
      return (await r.json()) as SeedStatus
    },
  })
}

export function useLoadSeed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const r = await apiFetch('/api/v2/admin/seed/load', { method: 'POST' })
      if (!r.ok) {
        const detail = await r.text()
        throw new Error(`seed load failed (${r.status}): ${detail}`)
      }
      return (await r.json()) as SeedLoadResult
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['seed'] })
      // Also invalidate cases / investors lists so the new seed rows
      // surface immediately in the UI.
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['investors'] })
    },
  })
}

export function useResetSeed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const r = await apiFetch('/api/v2/admin/seed/reset', { method: 'POST' })
      if (!r.ok) {
        const detail = await r.text()
        throw new Error(`seed reset failed (${r.status}): ${detail}`)
      }
      return (await r.json()) as SeedResetResult
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['seed'] })
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['investors'] })
    },
  })
}
