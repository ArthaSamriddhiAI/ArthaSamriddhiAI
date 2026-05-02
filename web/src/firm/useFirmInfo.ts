import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { apiFetch } from '../api/client'

// `firm-info` query + side-effect that writes branding to CSS variables.
// Mirrors the FirmInfo Pydantic model in
// src/artha/api_v2/system/firm_info.py.

export interface FirmBranding {
  primary_color: string
  accent_color: string
  logo_url: string
}

export interface FirmInfo {
  firm_id: string
  firm_name: string
  firm_display_name: string
  branding: FirmBranding
  feature_flags: Record<string, unknown>
  regulatory_jurisdiction: string
}

export function useFirmInfo() {
  return useQuery<FirmInfo>({
    queryKey: ['firm-info'],
    queryFn: async () => {
      const response = await apiFetch('/api/v2/system/firm-info')
      if (!response.ok) {
        throw new Error(`firm-info failed: ${response.status}`)
      }
      return response.json() as Promise<FirmInfo>
    },
    // Firm config changes rarely; cache aggressively.
    staleTime: 5 * 60 * 1000,
  })
}

// Apply firm branding to document root CSS variables. Per Cluster 0
// Ideation Log §4.1: --color-primary, --color-accent, --logo-url.
// Tailwind's bg-primary / text-accent utilities (configured in
// tailwind.config.js) resolve through these variables.
export function useApplyFirmBranding(firm: FirmInfo | undefined): void {
  useEffect(() => {
    if (!firm) return
    const root = document.documentElement
    root.style.setProperty('--color-primary', firm.branding.primary_color)
    root.style.setProperty('--color-accent', firm.branding.accent_color)
    // CSS url() wrapper so the value works in `background-image` etc.
    root.style.setProperty('--logo-url', `url('${firm.branding.logo_url}')`)
  }, [firm])
}
