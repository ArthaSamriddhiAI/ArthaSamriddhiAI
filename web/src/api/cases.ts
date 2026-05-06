import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './client'

// Mirrors src/artha/api_v2/cases/schemas.py.
// Cluster 5 chunk 5.5 case detail UI consumes these read shapes; chunks
// 5.3 / 5.4 ship the underlying endpoints, chunk 5.5 wires the React UI.

export type CaseMode = 'proposed_action' | 'scenario' | 'diagnostic' | 'briefing'
export type CaseStatus =
  | 'opening'
  | 'gathering_evidence'
  | 'synthesizing'
  | 'awaiting_committee'
  | 'awaiting_governance'
  | 'awaiting_challenge'
  | 'awaiting_decision'
  | 'decided'
  | 'archived'
  | 'failed'

export type CaseIntent =
  | 'rebalance_proposal'
  | 'new_investment'
  | 'exit_position'
  | 'product_evaluation'
  | 'asset_allocation_change'
  | 'tax_loss_harvesting'
  | 'liquidity_mobilisation'
  | 'mandate_review_response'
  | 'portfolio_health'
  | 'meeting_prep'
  | 'other'

export type DecisionVerdict = 'approved' | 'rejected' | 'modified' | 'deferred'

export interface Case {
  case_id: string
  investor_id: string
  household_id: string | null
  opened_by: string
  assigned_to: string
  case_mode: CaseMode
  case_intent: CaseIntent | null
  dominant_lens: 'portfolio_shift' | 'proposal_evaluation' | null
  proposed_action: string | null
  proposed_action_amount_inr: string | null
  proposed_action_products: string[]
  materiality_manual_flag: boolean
  status: CaseStatus
  status_changed_at: string
  snapshot_bundle_id: string | null
  materiality_assessed_at: string | null
  is_material: boolean | null
  materiality_reason: string | null
  total_llm_cost_inr: string
  total_llm_input_tokens: number
  total_llm_output_tokens: number
  created_at: string
  created_via: string
  closed_at: string | null
  closed_reason: string | null
  applicable_evidence_agents: string[]
  supersedes_case_id: string | null
  is_seed_data: boolean
  seed_archetype_id: string | null
  schema_version: number
}

export interface CaseListResponse {
  cases: Case[]
  total: number
  limit: number
  offset: number
}

export interface EvidenceVerdict {
  verdict_id: string
  case_id: string
  agent_id: string
  produced_at: string
  produced_via: string
  risk_level: 'low' | 'medium' | 'high' | 'critical' | null
  confidence: string | null
  drivers: Record<string, unknown> | null
  flags: Record<string, unknown> | null
  structured_output: Record<string, unknown> | null
  reasoning_summary: string | null
  schema_version: number
  is_seed_data: boolean
}

export interface SynthesisOutput {
  synthesis_id: string
  case_id: string
  produced_at: string
  produced_via: string
  output_mode: string
  consensus: Record<string, unknown> | null
  agreement_areas: Record<string, unknown> | null
  conflict_areas: Record<string, unknown> | null
  uncertainty_flag: boolean | null
  amplification: Record<string, unknown> | null
  mode_dominance: string | null
  escalation_recommended: boolean | null
  escalation_reason: string | null
  synthesis_narrative: string | null
  recommendation: string | null
  flags: Record<string, unknown> | null
  reasoning_summary: string | null
  schema_version: number
  is_seed_data: boolean
}

export interface PortfolioRiskAnalytics {
  output_id: string
  case_id: string
  produced_at: string
  produced_via: string
  concentration_assessment: Record<string, unknown> | null
  leverage_assessment: Record<string, unknown> | null
  liquidity_assessment: Record<string, unknown> | null
  return_quality_assessment: Record<string, unknown> | null
  deployment_assessment: Record<string, unknown> | null
  cascade_assessment: Record<string, unknown> | null
  overall_risk_level: string | null
  overall_confidence: string | null
  drivers: Record<string, unknown> | null
  flags: Record<string, unknown> | null
  reasoning_summary: string | null
  schema_version: number
  is_seed_data: boolean
}

export interface IC1Deliberation {
  deliberation_id: string
  case_id: string
  produced_at: string
  produced_via: string
  chair_summary: string | null
  devils_advocate_position: string | null
  risk_assessment: Record<string, unknown> | null
  counterfactual_engine_output: Record<string, unknown> | null
  minutes: Record<string, unknown>
  dissent: Record<string, unknown> | null
  recommendation: string
  conditions: Record<string, unknown> | null
  escalation_to_human: boolean
  reasoning_summary: string | null
  schema_version: number
  is_seed_data: boolean
}

export interface GovernanceResult {
  result_id: string
  case_id: string
  gate: 'g1_mandate' | 'g2_sebi_regulatory' | 'g3_action_filter'
  produced_at: string
  produced_via: string
  outcome: 'approved' | 'blocked' | 'escalation_required'
  blocking_rule_id: string | null
  blocking_rule_text: string | null
  reasoning: string | null
  override_requirements: Record<string, unknown> | null
  conditions_to_attach: Record<string, unknown> | null
  rule_corpus_version: string | null
  schema_version: number
  is_seed_data: boolean
}

export interface A1Challenge {
  challenge_id: string
  case_id: string
  produced_at: string
  produced_via: string
  counter_arguments: Record<string, unknown> | null
  alternative_proposals: Record<string, unknown> | null
  stress_test_scenarios: Record<string, unknown> | null
  edge_cases: Record<string, unknown> | null
  accountability_flags: Record<string, unknown> | null
  reasoning_summary: string | null
  schema_version: number
  is_seed_data: boolean
}

export interface DecisionArtifact {
  artifact_id: string
  case_id: string
  decided_at: string
  decided_by: string
  decision: DecisionVerdict
  modifications: Record<string, unknown> | null
  rationale: string
  conditions: Record<string, unknown> | null
  evidence_packet_hash: string
  synthesis_hash: string
  governance_packet_hash: string
  portfolio_risk_hash: string | null
  ic1_hash: string | null
  a1_hash: string | null
  schema_version: number
  is_seed_data: boolean
}

export interface BriefingNote {
  briefing_id: string
  case_id: string
  produced_at: string
  produced_via: string
  meeting_context: string | null
  recent_activity_summary: string | null
  current_state_summary: string | null
  market_context: string | null
  prep_questions: Record<string, unknown> | null
  schema_version: number
  is_seed_data: boolean
}

export interface HealthReport {
  report_id: string
  case_id: string
  produced_at: string
  produced_via: string
  overall_health: 'healthy' | 'attention_needed' | 'urgent'
  asset_allocation_status: Record<string, unknown> | null
  performance_summary: Record<string, unknown> | null
  drift_indicators: Record<string, unknown> | null
  recommendations: Record<string, unknown> | null
  schema_version: number
  is_seed_data: boolean
}

export interface CaseDetailResponse {
  case: Case
  evidence_verdicts: EvidenceVerdict[]
  portfolio_risk_analytics: PortfolioRiskAnalytics | null
  synthesis: SynthesisOutput | null
  ic1_deliberation: IC1Deliberation | null
  governance_results: GovernanceResult[]
  a1_challenge: A1Challenge | null
  decision_artifact: DecisionArtifact | null
  briefing_note: BriefingNote | null
  health_report: HealthReport | null
}

// ---- create payload + decision payload ----

export interface CaseCreatePayload {
  investor_id: string
  case_mode: CaseMode
  case_intent?: CaseIntent
  dominant_lens?: 'portfolio_shift' | 'proposal_evaluation'
  proposed_action?: string
  proposed_action_amount_inr?: string
  proposed_action_products?: string[]
  materiality_manual_flag?: boolean
  supersedes_case_id?: string
  manual_override_evidence_agents?: string[]
}

export interface DecisionRecordPayload {
  decision: DecisionVerdict
  rationale: string
  modifications?: Record<string, unknown>
  conditions?: Record<string, unknown>
}

export interface CaseListFilters {
  investor_id?: string
  assigned_to?: string
  status?: CaseStatus
  case_mode?: CaseMode
  limit?: number
  offset?: number
}

// ---- queries ----

function buildQueryString(filters: CaseListFilters): string {
  const params = new URLSearchParams()
  if (filters.investor_id) params.set('investor_id', filters.investor_id)
  if (filters.assigned_to) params.set('assigned_to', filters.assigned_to)
  if (filters.status) params.set('status', filters.status)
  if (filters.case_mode) params.set('case_mode', filters.case_mode)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const s = params.toString()
  return s ? `?${s}` : ''
}

export function useCasesList(filters: CaseListFilters = {}) {
  return useQuery<CaseListResponse>({
    queryKey: ['cases', 'list', filters],
    queryFn: async () => {
      const qs = buildQueryString(filters)
      const r = await apiFetch(`/api/v2/cases${qs}`)
      if (!r.ok) throw new Error(`cases list failed: ${r.status}`)
      return (await r.json()) as CaseListResponse
    },
  })
}

export function useCase(caseId: string | undefined) {
  return useQuery<Case>({
    queryKey: ['cases', 'detail', caseId],
    enabled: Boolean(caseId),
    queryFn: async () => {
      const r = await apiFetch(`/api/v2/cases/${caseId}`)
      if (!r.ok) throw new Error(`case fetch failed: ${r.status}`)
      return (await r.json()) as Case
    },
  })
}

export function useCaseDetail(caseId: string | undefined) {
  return useQuery<CaseDetailResponse>({
    queryKey: ['cases', 'detail-full', caseId],
    enabled: Boolean(caseId),
    queryFn: async () => {
      const r = await apiFetch(`/api/v2/cases/${caseId}/detail`)
      if (!r.ok) throw new Error(`case detail failed: ${r.status}`)
      return (await r.json()) as CaseDetailResponse
    },
  })
}

// ---- mutations ----

export function useCreateCase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: CaseCreatePayload) => {
      const r = await apiFetch('/api/v2/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) {
        const detail = await r.text()
        throw new Error(`case create failed (${r.status}): ${detail}`)
      }
      return (await r.json()) as Case
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases'] })
    },
  })
}

export function useRecordDecision(caseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: DecisionRecordPayload) => {
      const r = await apiFetch(`/api/v2/cases/${caseId}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) {
        const detail = await r.text()
        throw new Error(`decision record failed (${r.status}): ${detail}`)
      }
      return (await r.json()) as DecisionArtifact
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases'] })
    },
  })
}

// ---- formatting helpers ----

export function formatStatus(status: CaseStatus): string {
  return status
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function formatMode(mode: CaseMode): string {
  return formatStatus(mode as unknown as CaseStatus)
}

export const CASE_MODE_OPTIONS: Array<{ value: CaseMode; label: string }> = [
  { value: 'proposed_action', label: 'Proposed Action' },
  { value: 'scenario', label: 'Scenario' },
  { value: 'diagnostic', label: 'Diagnostic' },
  { value: 'briefing', label: 'Briefing' },
]

export const CASE_INTENT_OPTIONS: Array<{ value: CaseIntent; label: string; modes: CaseMode[] }> = [
  { value: 'rebalance_proposal', label: 'Rebalance Proposal', modes: ['proposed_action', 'scenario'] },
  { value: 'new_investment', label: 'New Investment', modes: ['proposed_action', 'scenario'] },
  { value: 'exit_position', label: 'Exit Position', modes: ['proposed_action', 'scenario'] },
  { value: 'product_evaluation', label: 'Product Evaluation', modes: ['proposed_action', 'scenario'] },
  { value: 'asset_allocation_change', label: 'Asset Allocation Change', modes: ['proposed_action', 'scenario'] },
  { value: 'tax_loss_harvesting', label: 'Tax Loss Harvesting', modes: ['proposed_action', 'scenario'] },
  { value: 'liquidity_mobilisation', label: 'Liquidity Mobilisation', modes: ['proposed_action', 'scenario'] },
  { value: 'mandate_review_response', label: 'Mandate Review Response', modes: ['proposed_action', 'scenario'] },
  { value: 'other', label: 'Other', modes: ['proposed_action', 'scenario'] },
  { value: 'portfolio_health', label: 'Portfolio Health', modes: ['diagnostic'] },
  { value: 'meeting_prep', label: 'Meeting Prep', modes: ['briefing'] },
]
