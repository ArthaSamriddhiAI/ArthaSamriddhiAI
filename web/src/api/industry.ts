import { useQuery } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/d0/industry/schemas.py.

export type IndustryOutlook = 'positive' | 'neutral' | 'negative'

export interface IndustryReport {
  industry_report_id: string

  industry_code: string
  industry_name: string
  report_period: string
  report_date: string

  outlook: IndustryOutlook
  summary: string
  key_themes: string[]
  drivers: string[]
  risks: string[]

  source_identifier: string
  source_subkey: string | null
  staging_record_id: string | null
  adapter_run_id: string | null

  created_at: string
  last_modified_at: string
  schema_version: number
}

export interface IndustryReportListResponse {
  reports: IndustryReport[]
  total: number
  limit: number
  offset: number
}

export interface IndustryReportFilters {
  industry_code?: string
  outlook?: IndustryOutlook
  report_period?: string
  limit?: number
  offset?: number
}

function buildQuery(filters: IndustryReportFilters): string {
  const params = new URLSearchParams()
  if (filters.industry_code) params.set('industry_code', filters.industry_code)
  if (filters.outlook) params.set('outlook', filters.outlook)
  if (filters.report_period) params.set('report_period', filters.report_period)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export function useIndustryReports(filters: IndustryReportFilters = {}) {
  return useQuery<IndustryReportListResponse>({
    queryKey: ['industry-reports', 'list', filters],
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/admin/industry-reports${buildQuery(filters)}`,
      )
      if (!r.ok) {
        throw new Error(`industry-reports fetch failed: ${r.status}`)
      }
      return (await r.json()) as IndustryReportListResponse
    },
  })
}

export function useIndustryReport(industryReportId: string | undefined) {
  return useQuery<IndustryReport>({
    queryKey: ['industry-reports', 'detail', industryReportId],
    enabled: Boolean(industryReportId),
    queryFn: async () => {
      const r = await apiFetch(
        `/api/v2/admin/industry-reports/${industryReportId}`,
      )
      if (!r.ok) {
        throw new Error(`industry-report fetch failed: ${r.status}`)
      }
      return (await r.json()) as IndustryReport
    },
  })
}
