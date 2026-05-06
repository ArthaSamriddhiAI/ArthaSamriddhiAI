import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/m2/schemas.py.
// Cluster 4 chunk 4.1 read-only API surface; chunks 4.2 / 4.3 add write
// hooks (PUT tags, POST entries, etc.) on top of these read shapes.

export type RiskProfile = 'aggressive' | 'moderate' | 'conservative'
export type Horizon = 'long_term' | 'medium_term' | 'short_term'
export type PositionRole = 'core' | 'satellite' | 'optional'

export const ALL_RISK_PROFILES: RiskProfile[] = [
  'aggressive',
  'moderate',
  'conservative',
]

export const ALL_HORIZONS: Horizon[] = [
  'long_term',
  'medium_term',
  'short_term',
]

export function cellId(rp: RiskProfile, h: Horizon): string {
  return `${rp}_${h}`
}

export function splitCell(id: string): [RiskProfile, Horizon] | null {
  for (const rp of ALL_RISK_PROFILES) {
    const prefix = `${rp}_`
    if (id.startsWith(prefix)) {
      const h = id.slice(prefix.length) as Horizon
      if (ALL_HORIZONS.includes(h)) {
        return [rp, h]
      }
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// Investor → cell mapping (FR 11.0 cluster-4 revision §2.1)
// ---------------------------------------------------------------------------

const HORIZON_MAP: Record<string, Horizon> = {
  over_5_years: 'long_term',
  '3_to_5_years': 'medium_term',
  under_3_years: 'short_term',
}

export function investorToCell(opts: {
  riskAppetite?: string | null
  timeHorizon?: string | null
}): string | null {
  if (!opts.riskAppetite || !opts.timeHorizon) return null
  if (!ALL_RISK_PROFILES.includes(opts.riskAppetite as RiskProfile)) return null
  const h = HORIZON_MAP[opts.timeHorizon]
  if (!h) return null
  return `${opts.riskAppetite}_${h}`
}

// ---------------------------------------------------------------------------
// Instrument-with-tags shapes
// ---------------------------------------------------------------------------

export interface InstrumentWithTags {
  instrument_id: string
  isin: string | null
  amfi_scheme_code: string | null
  exchange_ticker: string | null
  name: string
  asset_class: string
  vehicle_type: string
  sebi_category: string | null
  amc_name: string | null
  riskometer_label: string | null
  status: string
  inception_date: string | null
  model_portfolio_tags: string[]
  model_portfolio_tags_modified_at: string | null
  model_portfolio_tags_modified_by: string | null
  last_modified_at: string
  schema_version: number
}

export interface InstrumentListResponse {
  instruments: InstrumentWithTags[]
  total: number
  limit: number
  offset: number
}

export interface InstrumentFilters {
  asset_class?: string
  vehicle_type?: string
  sebi_category?: string
  tag_include?: string[]
  tag_exclude?: string[]
  untagged_only?: boolean
  search?: string
  limit?: number
  offset?: number
}

function buildInstrumentQuery(f: InstrumentFilters): string {
  const params = new URLSearchParams()
  if (f.asset_class) params.set('asset_class', f.asset_class)
  if (f.vehicle_type) params.set('vehicle_type', f.vehicle_type)
  if (f.sebi_category) params.set('sebi_category', f.sebi_category)
  if (f.tag_include) f.tag_include.forEach((t) => params.append('tag_include', t))
  if (f.tag_exclude) f.tag_exclude.forEach((t) => params.append('tag_exclude', t))
  if (f.untagged_only) params.set('untagged_only', 'true')
  if (f.search) params.set('search', f.search)
  if (f.limit !== undefined) params.set('limit', String(f.limit))
  if (f.offset !== undefined) params.set('offset', String(f.offset))
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export function useModelPortfolioInstruments(filters: InstrumentFilters = {}) {
  return useQuery<InstrumentListResponse>({
    queryKey: ['model-portfolio', 'instruments', filters],
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/instruments${buildInstrumentQuery(filters)}`,
      )
      if (!r.ok) throw new Error(`instruments fetch failed: ${r.status}`)
      return (await r.json()) as InstrumentListResponse
    },
  })
}

export function useModelPortfolioInstrument(instrumentId: string | undefined) {
  return useQuery<InstrumentWithTags>({
    queryKey: ['model-portfolio', 'instrument', instrumentId],
    enabled: Boolean(instrumentId),
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/instruments/${instrumentId}`,
      )
      if (!r.ok) throw new Error(`instrument fetch failed: ${r.status}`)
      return (await r.json()) as InstrumentWithTags
    },
  })
}

// ---------------------------------------------------------------------------
// Preferred portfolio shapes
// ---------------------------------------------------------------------------

export interface CellRoleSummary {
  core: number
  satellite: number
  optional: number
}

export interface CellSummary {
  risk_profile: RiskProfile
  horizon: Horizon
  cell_id: string
  counts: CellRoleSummary
  last_modified_at: string | null
  top_core_names: string[]
}

export interface MatrixOverviewResponse {
  cells: CellSummary[]
  total_entries: number
  last_modified_at: string | null
}

export interface PreferredPortfolioEntry {
  entry_id: string
  risk_profile: RiskProfile
  horizon: Horizon
  instrument_id: string
  instrument_name: string
  instrument_asset_class: string
  instrument_vehicle_type: string
  instrument_amc_name: string | null
  instrument_sebi_category: string | null
  position_role: PositionRole
  rank_within_role: number
  notes: string | null
  has_matching_tag: boolean
  created_at: string
  created_by: string
  created_via: string
  last_modified_at: string
  last_modified_by: string
}

export interface CellDetailResponse {
  risk_profile: RiskProfile
  horizon: Horizon
  cell_id: string
  core: PreferredPortfolioEntry[]
  satellite: PreferredPortfolioEntry[]
  optional: PreferredPortfolioEntry[]
  last_modified_at: string | null
}

export interface InstrumentInPreferredEntry {
  entry_id: string
  risk_profile: RiskProfile
  horizon: Horizon
  cell_id: string
  position_role: PositionRole
  rank_within_role: number
}

export interface InstrumentInPreferredResponse {
  instrument_id: string
  instrument_name: string
  appearances: InstrumentInPreferredEntry[]
}

export function useMatrixOverview() {
  return useQuery<MatrixOverviewResponse>({
    queryKey: ['model-portfolio', 'preferred', 'matrix'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/model-portfolio/preferred')
      if (!r.ok) throw new Error(`matrix fetch failed: ${r.status}`)
      return (await r.json()) as MatrixOverviewResponse
    },
  })
}

export function useCellDetail(
  riskProfile: RiskProfile | undefined,
  horizon: Horizon | undefined,
) {
  return useQuery<CellDetailResponse>({
    queryKey: ['model-portfolio', 'preferred', 'cell', riskProfile, horizon],
    enabled: Boolean(riskProfile && horizon),
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/preferred/${riskProfile}/${horizon}`,
      )
      if (!r.ok) throw new Error(`cell fetch failed: ${r.status}`)
      return (await r.json()) as CellDetailResponse
    },
  })
}

export function useInstrumentInPreferred(instrumentId: string | undefined) {
  return useQuery<InstrumentInPreferredResponse>({
    queryKey: ['model-portfolio', 'preferred', 'by-instrument', instrumentId],
    enabled: Boolean(instrumentId),
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/preferred/by-instrument/${instrumentId}`,
      )
      if (!r.ok) throw new Error(`by-instrument fetch failed: ${r.status}`)
      return (await r.json()) as InstrumentInPreferredResponse
    },
  })
}

// ---------------------------------------------------------------------------
// Health summary
// ---------------------------------------------------------------------------

export interface ModelPortfolioHealth {
  tagged_instruments_count: number
  untagged_instruments_count: number
  total_instruments: number
  total_preferred_entries: number
  preferred_entries_by_cell: Record<string, CellRoleSummary>
  last_tag_modification_at: string | null
  last_preferred_modification_at: string | null
}

export function useModelPortfolioHealth() {
  return useQuery<ModelPortfolioHealth>({
    queryKey: ['model-portfolio', 'health'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/model-portfolio/health')
      if (!r.ok) throw new Error(`health fetch failed: ${r.status}`)
      return (await r.json()) as ModelPortfolioHealth
    },
  })
}

// ---------------------------------------------------------------------------
// Chunk 4.2 mutation hooks (CIO-only writes)
// ---------------------------------------------------------------------------

export interface BulkTagOperationResponse {
  affected_count: number
  skipped_count: number
  failed_count: number
  operation: string
}

function invalidateModelPortfolio(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ['model-portfolio'] })
}

export function useReplaceInstrumentTags() {
  const qc = useQueryClient()
  return useMutation<
    InstrumentWithTags,
    Error,
    { instrumentId: string; tags: string[] }
  >({
    mutationFn: async ({ instrumentId, tags }) => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/instruments/${instrumentId}/tags`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tags }),
        },
      )
      if (!r.ok) {
        const detail = (await r.json().catch(() => ({}))) as Record<string, unknown>
        throw new Error(
          (detail.detail as string) ?? `tag replace failed: ${r.status}`,
        )
      }
      return (await r.json()) as InstrumentWithTags
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useBulkAddTag() {
  const qc = useQueryClient()
  return useMutation<
    BulkTagOperationResponse,
    Error,
    { tag: string; instrumentIds: string[] }
  >({
    mutationFn: async ({ tag, instrumentIds }) => {
      const r = await apiFetch(
        '/api/v2/model-portfolio/instruments/tags/bulk-add',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tag, instrument_ids: instrumentIds }),
        },
      )
      if (!r.ok) throw new Error(`bulk-add failed: ${r.status}`)
      return (await r.json()) as BulkTagOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useBulkRemoveTag() {
  const qc = useQueryClient()
  return useMutation<
    BulkTagOperationResponse,
    Error,
    { tag: string; instrumentIds: string[] }
  >({
    mutationFn: async ({ tag, instrumentIds }) => {
      const r = await apiFetch(
        '/api/v2/model-portfolio/instruments/tags/bulk-remove',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tag, instrument_ids: instrumentIds }),
        },
      )
      if (!r.ok) throw new Error(`bulk-remove failed: ${r.status}`)
      return (await r.json()) as BulkTagOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useBulkReplaceTags() {
  const qc = useQueryClient()
  return useMutation<
    BulkTagOperationResponse,
    Error,
    { tags: string[]; instrumentIds: string[] }
  >({
    mutationFn: async ({ tags, instrumentIds }) => {
      const r = await apiFetch(
        '/api/v2/model-portfolio/instruments/tags/bulk-replace',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tags, instrument_ids: instrumentIds }),
        },
      )
      if (!r.ok) throw new Error(`bulk-replace failed: ${r.status}`)
      return (await r.json()) as BulkTagOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useResetTagsToDefault() {
  const qc = useQueryClient()
  return useMutation<
    BulkTagOperationResponse,
    Error,
    { instrumentIds: string[] }
  >({
    mutationFn: async ({ instrumentIds }) => {
      const r = await apiFetch(
        '/api/v2/model-portfolio/instruments/tags/reset-to-default',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instrument_ids: instrumentIds }),
        },
      )
      if (!r.ok) throw new Error(`reset failed: ${r.status}`)
      return (await r.json()) as BulkTagOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

// ---------------------------------------------------------------------------
// Chunk 4.3 preferred-portfolio mutation hooks
// ---------------------------------------------------------------------------

export interface CellOperationResponse {
  risk_profile: RiskProfile
  horizon: Horizon
  affected_count: number
  skipped_count: number
  operation: string
}

export function useCreatePreferredEntry() {
  const qc = useQueryClient()
  return useMutation<
    PreferredPortfolioEntry,
    Error,
    {
      riskProfile: RiskProfile
      horizon: Horizon
      instrumentId: string
      positionRole: PositionRole
      rankWithinRole: number
      notes?: string
    }
  >({
    mutationFn: async (input) => {
      const r = await apiFetch('/api/v2/model-portfolio/preferred', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          risk_profile: input.riskProfile,
          horizon: input.horizon,
          instrument_id: input.instrumentId,
          position_role: input.positionRole,
          rank_within_role: input.rankWithinRole,
          notes: input.notes,
        }),
      })
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as Record<string, unknown>
        throw new Error((body.detail as string) ?? `create failed: ${r.status}`)
      }
      return (await r.json()) as PreferredPortfolioEntry
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useUpdatePreferredEntry() {
  const qc = useQueryClient()
  return useMutation<
    PreferredPortfolioEntry,
    Error,
    {
      entryId: string
      positionRole?: PositionRole
      rankWithinRole?: number
      notes?: string | null
    }
  >({
    mutationFn: async (input) => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/preferred/${input.entryId}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            position_role: input.positionRole,
            rank_within_role: input.rankWithinRole,
            notes: input.notes,
          }),
        },
      )
      if (!r.ok) throw new Error(`update failed: ${r.status}`)
      return (await r.json()) as PreferredPortfolioEntry
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useDeletePreferredEntry() {
  const qc = useQueryClient()
  return useMutation<void, Error, { entryId: string }>({
    mutationFn: async ({ entryId }) => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/preferred/${entryId}`,
        { method: 'DELETE' },
      )
      if (!r.ok) throw new Error(`delete failed: ${r.status}`)
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useReorderCell() {
  const qc = useQueryClient()
  return useMutation<
    CellOperationResponse,
    Error,
    {
      riskProfile: RiskProfile
      horizon: Horizon
      items: Array<{
        entry_id: string
        position_role: PositionRole
        rank_within_role: number
      }>
    }
  >({
    mutationFn: async ({ riskProfile, horizon, items }) => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/preferred/${riskProfile}/${horizon}/reorder`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items }),
        },
      )
      if (!r.ok) throw new Error(`reorder failed: ${r.status}`)
      return (await r.json()) as CellOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useDuplicateCell() {
  const qc = useQueryClient()
  return useMutation<
    CellOperationResponse,
    Error,
    {
      targetRiskProfile: RiskProfile
      targetHorizon: Horizon
      sourceRiskProfile: RiskProfile
      sourceHorizon: Horizon
      onlyMatchingTags?: boolean
      skipExisting?: boolean
    }
  >({
    mutationFn: async (input) => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/preferred/${input.targetRiskProfile}/${input.targetHorizon}/duplicate-from`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_risk_profile: input.sourceRiskProfile,
            source_horizon: input.sourceHorizon,
            only_matching_tags: input.onlyMatchingTags ?? true,
            skip_existing: input.skipExisting ?? true,
          }),
        },
      )
      if (!r.ok) throw new Error(`duplicate failed: ${r.status}`)
      return (await r.json()) as CellOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useResetCellToDefault() {
  const qc = useQueryClient()
  return useMutation<
    CellOperationResponse,
    Error,
    { riskProfile: RiskProfile; horizon: Horizon }
  >({
    mutationFn: async ({ riskProfile, horizon }) => {
      const r = await apiFetch(
        `/api/v2/model-portfolio/preferred/${riskProfile}/${horizon}/reset-to-default`,
        { method: 'POST' },
      )
      if (!r.ok) throw new Error(`reset cell failed: ${r.status}`)
      return (await r.json()) as CellOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}

export function useResetAllPreferred() {
  const qc = useQueryClient()
  return useMutation<CellOperationResponse, Error, void>({
    mutationFn: async () => {
      const r = await apiFetch(
        '/api/v2/model-portfolio/preferred/reset-to-default',
        { method: 'POST' },
      )
      if (!r.ok) throw new Error(`reset all failed: ${r.status}`)
      return (await r.json()) as CellOperationResponse
    },
    onSuccess: () => invalidateModelPortfolio(qc),
  })
}
