import { useQuery } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/d0/instruments/schemas.py.
// Cluster 3 chunk 3.2 surfaces. Chunk 3.4 wires these into the audit-role
// admin UI; this module ships the shared types + react-query hooks now so
// chunk 3.4's UI work is a thin layer over the typed API.

export type AssetClass = 'equity' | 'debt' | 'cash' | 'alternatives'
export type VehicleType = 'mutual_fund' | 'etf' | 'stock' | 'bond'
export type ClassificationConfidence = 'high' | 'medium' | 'low'
export type InstrumentStatus = 'active' | 'suspended' | 'delisted'

export interface Instrument {
  instrument_id: string

  // Identifiers
  isin: string | null
  amfi_scheme_code: string | null
  exchange_ticker: string | null
  name: string
  short_name: string | null

  // Classification
  asset_class: AssetClass
  vehicle_type: VehicleType
  sebi_category: string | null
  sebi_subcategory: string | null
  classification_confidence: ClassificationConfidence

  // Issuer / fund house
  issuer_name: string | null
  amc_name: string | null

  // Risk
  riskometer_label: string | null

  // Status + lifecycle
  status: InstrumentStatus
  inception_date: string | null

  // Source lineage
  source_identifier: string
  source_subkey: string | null
  staging_record_id: string | null
  adapter_run_id: string | null

  // Provenance
  created_at: string
  last_modified_at: string
  schema_version: number
}

export interface InstrumentListResponse {
  instruments: Instrument[]
  total: number
  limit: number
  offset: number
}

export interface SebiCategoryEntry {
  category: string
  asset_class: AssetClass
  vehicle_type: VehicleType
}

export interface SebiCategoriesResponse {
  categories: SebiCategoryEntry[]
}

export interface InstrumentFilters {
  asset_class?: AssetClass
  vehicle_type?: VehicleType
  sebi_category?: string
  instrument_status?: InstrumentStatus
  search?: string
  limit?: number
  offset?: number
}

function buildQuery(filters: InstrumentFilters): string {
  const params = new URLSearchParams()
  if (filters.asset_class) params.set('asset_class', filters.asset_class)
  if (filters.vehicle_type) params.set('vehicle_type', filters.vehicle_type)
  if (filters.sebi_category) params.set('sebi_category', filters.sebi_category)
  if (filters.instrument_status)
    params.set('instrument_status', filters.instrument_status)
  if (filters.search) params.set('search', filters.search)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export function useInstruments(filters: InstrumentFilters = {}) {
  return useQuery<InstrumentListResponse>({
    queryKey: ['instruments', 'list', filters],
    queryFn: async () => {
      const r = await apiFetch(`/api/v2/admin/instruments${buildQuery(filters)}`)
      if (!r.ok) {
        throw new Error(`instruments fetch failed: ${r.status}`)
      }
      return (await r.json()) as InstrumentListResponse
    },
  })
}

export function useInstrument(instrumentId: string | undefined) {
  return useQuery<Instrument>({
    queryKey: ['instruments', 'detail', instrumentId],
    enabled: Boolean(instrumentId),
    queryFn: async () => {
      const r = await apiFetch(`/api/v2/admin/instruments/${instrumentId}`)
      if (!r.ok) {
        throw new Error(`instrument fetch failed: ${r.status}`)
      }
      return (await r.json()) as Instrument
    },
  })
}

export function useSebiCategories() {
  return useQuery<SebiCategoriesResponse>({
    queryKey: ['instruments', 'sebi-categories'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/admin/sebi-categories')
      if (!r.ok) {
        throw new Error(`sebi-categories fetch failed: ${r.status}`)
      }
      return (await r.json()) as SebiCategoriesResponse
    },
    staleTime: 1000 * 60 * 60, // categories don't change at runtime; cache aggressively
  })
}
