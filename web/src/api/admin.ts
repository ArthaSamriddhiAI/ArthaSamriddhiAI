import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './client'

// Cluster 3 chunk 3.4 — typed admin surface for the audit-role pages.
// Mirrors src/artha/api_v2/d0/{router,snapshot/router,instruments/router,
// macro/router,industry/router}.py.

// ---------------------------------------------------------------------------
// Adapters
// ---------------------------------------------------------------------------


export interface AdapterStatus {
  source_identifier: string
  supported_entity_types: string[]
  healthy: boolean
  last_successful_fetch_at: string | null
  last_error_message: string | null
}


export interface AdapterListResponse {
  adapters: AdapterStatus[]
}


export interface AdapterRunRequest {
  mode: 'full' | 'validation'
}


export interface AdapterRunResponse {
  run_id: string
  status: 'success' | 'partial_success' | 'failure'
  started_at: string
  completed_at: string
  staging_records_created: number
  canonical_entities_created: Record<string, number>
  canonical_entities_updated: Record<string, number>
  error_count: number
  metadata: Record<string, unknown>
}


export function useAdapters() {
  return useQuery<AdapterListResponse>({
    queryKey: ['admin', 'adapters'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/admin/adapters')
      if (!r.ok) throw new Error(`adapters fetch failed: ${r.status}`)
      return (await r.json()) as AdapterListResponse
    },
  })
}


export function useRunAdapter(sourceIdentifier: string) {
  const qc = useQueryClient()
  return useMutation<AdapterRunResponse, Error, AdapterRunRequest>({
    mutationFn: async (body) => {
      const r = await apiFetch(
        `/api/v2/admin/adapters/${sourceIdentifier}/run`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
      if (!r.ok) throw new Error(`adapter run failed: ${r.status}`)
      return (await r.json()) as AdapterRunResponse
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin'] })
      void qc.invalidateQueries({ queryKey: ['instruments'] })
      void qc.invalidateQueries({ queryKey: ['macro-snapshots'] })
      void qc.invalidateQueries({ queryKey: ['industry-reports'] })
    },
  })
}


// ---------------------------------------------------------------------------
// Staging records
// ---------------------------------------------------------------------------


export interface StagingRecord {
  staging_record_id: string
  source_identifier: string
  source_subkey: string | null
  adapter_run_id: string
  raw_content_format: string
  raw_content_hash: string
  raw_content_size_bytes: number
  fetched_at: string
  source_metadata: Record<string, unknown>
  created_at: string
}


export interface StagingRecordsListResponse {
  records: StagingRecord[]
}


export interface StagingFilters {
  source?: string
  adapter_run_id?: string
  limit?: number
}


export function useStagingRecords(filters: StagingFilters = {}) {
  return useQuery<StagingRecordsListResponse>({
    queryKey: ['admin', 'staging', filters],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filters.source) params.set('source', filters.source)
      if (filters.adapter_run_id)
        params.set('adapter_run_id', filters.adapter_run_id)
      if (filters.limit !== undefined)
        params.set('limit', String(filters.limit))
      const qs = params.toString()
      const url = qs
        ? `/api/v2/admin/staging?${qs}`
        : '/api/v2/admin/staging'
      const r = await apiFetch(url)
      if (!r.ok) throw new Error(`staging fetch failed: ${r.status}`)
      return (await r.json()) as StagingRecordsListResponse
    },
  })
}


// ---------------------------------------------------------------------------
// Freshness
// ---------------------------------------------------------------------------


export interface FreshnessRow {
  entity_table: string
  record_count: number
  latest_last_modified_at: string | null
  threshold_seconds: number
  threshold_human: string
  freshness_status: 'fresh' | 'stale' | 'very_stale'
  age_seconds: number
}


export interface FreshnessResponse {
  rows: FreshnessRow[]
}


export function useFreshness() {
  return useQuery<FreshnessResponse>({
    queryKey: ['admin', 'freshness'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/admin/data-freshness')
      if (!r.ok) throw new Error(`freshness fetch failed: ${r.status}`)
      return (await r.json()) as FreshnessResponse
    },
  })
}


// ---------------------------------------------------------------------------
// Snapshots
// ---------------------------------------------------------------------------


export interface SnapshotSummary {
  snapshot_id: string
  created_at: string
  created_by: string
  description: string | null
  trigger_type: string
  entity_counts: Record<string, number>
  content_hash: string
  serialised_payload_size_bytes: number
  associated_adapter_run_ids: string[]
  verified_at: string | null
  verified_status: 'never_verified' | 'verified' | 'verification_failed'
  schema_version: number
}


export interface SnapshotListResponse {
  snapshots: SnapshotSummary[]
  total: number
  limit: number
  offset: number
}


export interface SnapshotCreateRequest {
  description?: string
  trigger_type?: string
  trigger_context?: Record<string, unknown>
}


export interface SnapshotVerifyResponse {
  snapshot_id: string
  stored_hash: string
  recomputed_hash: string
  verified_status: SnapshotSummary['verified_status']
  verified_at: string | null
}


export function useSnapshots() {
  return useQuery<SnapshotListResponse>({
    queryKey: ['admin', 'snapshots'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/admin/snapshots')
      if (!r.ok) throw new Error(`snapshots fetch failed: ${r.status}`)
      return (await r.json()) as SnapshotListResponse
    },
  })
}


export function useCreateSnapshot() {
  const qc = useQueryClient()
  return useMutation<SnapshotSummary, Error, SnapshotCreateRequest>({
    mutationFn: async (body) => {
      const r = await apiFetch('/api/v2/admin/snapshots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`snapshot create failed: ${r.status}`)
      return (await r.json()) as SnapshotSummary
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'snapshots'] })
    },
  })
}


export function useVerifySnapshot() {
  const qc = useQueryClient()
  return useMutation<SnapshotVerifyResponse, Error, string>({
    mutationFn: async (snapshotId) => {
      const r = await apiFetch(
        `/api/v2/admin/snapshots/${snapshotId}/verify`,
        { method: 'POST' },
      )
      if (!r.ok) throw new Error(`snapshot verify failed: ${r.status}`)
      return (await r.json()) as SnapshotVerifyResponse
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'snapshots'] })
    },
  })
}
