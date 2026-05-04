import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/llm/schemas.py.
// All read shapes mask the API key — plaintext keys never round-trip
// through this client (per FR 16.0 §4.1).

export type ProviderName = 'mistral' | 'claude'

export interface LLMConfigRead {
  active_provider: ProviderName | null
  mistral_api_key_masked: string | null
  claude_api_key_masked: string | null
  default_mistral_model: string
  default_claude_model: string
  rate_limit_calls_per_minute: number
  request_timeout_seconds: number
  kill_switch_active: boolean
  is_configured: boolean
  updated_at: string | null
  updated_by: string | null
  supported_providers: string[]
}

export interface LLMConfigUpdatePayload {
  active_provider?: ProviderName | null
  // Plaintext on the wire from CIO browser → server. The server encrypts
  // before persisting; nothing further reads the plaintext after that.
  mistral_api_key?: string
  claude_api_key?: string
  default_mistral_model?: string
  default_claude_model?: string
}

export interface TestConnectionPayload {
  provider: ProviderName
  api_key?: string  // plaintext typed by the CIO; not stored client-side.
}

export interface TestConnectionResponse {
  success: boolean
  provider: ProviderName
  detail: string
  failure_type: string | null
  latency_ms: number | null
}

export interface KillSwitchResponse {
  kill_switch_active: boolean
  activated_at: string | null
  activated_by: string | null
}

export interface LLMStatusResponse {
  is_configured: boolean
}

export class LLMConfigError extends Error {
  readonly status: number
  readonly code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'LLMConfigError'
    this.status = status
    this.code = code
  }
}

// ---- queries ----

export function useLLMConfig() {
  return useQuery<LLMConfigRead>({
    queryKey: ['llm', 'config'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/llm/config')
      if (!r.ok) throw new Error(`LLM config fetch failed: ${r.status}`)
      return (await r.json()) as LLMConfigRead
    },
  })
}

export function useLLMStatus(opts?: { enabled?: boolean }) {
  return useQuery<LLMStatusResponse>({
    queryKey: ['llm', 'status'],
    enabled: opts?.enabled ?? true,
    queryFn: async () => {
      const r = await apiFetch('/api/v2/llm/status')
      if (!r.ok) throw new Error(`LLM status fetch failed: ${r.status}`)
      return (await r.json()) as LLMStatusResponse
    },
  })
}

// ---- mutations ----

export function useUpdateLLMConfig() {
  const qc = useQueryClient()
  return useMutation<LLMConfigRead, LLMConfigError, LLMConfigUpdatePayload>({
    mutationFn: async (payload) => {
      const r = await apiFetch('/api/v2/llm/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        const detail = (body as { detail?: string }).detail
        const code = (body as { code?: string }).code
        throw new LLMConfigError(
          detail ?? `Update failed (${r.status})`,
          r.status,
          code,
        )
      }
      return (await r.json()) as LLMConfigRead
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['llm'] })
    },
  })
}

export function useTestConnection() {
  return useMutation<TestConnectionResponse, Error, TestConnectionPayload>({
    mutationFn: async (payload) => {
      const r = await apiFetch('/api/v2/llm/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) throw new Error(`Test connection failed: ${r.status}`)
      return (await r.json()) as TestConnectionResponse
    },
  })
}

export function useKillSwitch() {
  const qc = useQueryClient()
  return useMutation<KillSwitchResponse, Error, 'activate' | 'deactivate'>({
    mutationFn: async (action) => {
      const r = await apiFetch(`/api/v2/llm/kill-switch/${action}`, {
        method: 'POST',
      })
      if (!r.ok) throw new Error(`Kill-switch ${action} failed: ${r.status}`)
      return (await r.json()) as KillSwitchResponse
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['llm'] })
    },
  })
}
