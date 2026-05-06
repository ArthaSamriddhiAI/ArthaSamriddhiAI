import { Link, useParams } from '@tanstack/react-router'

import { useCaseDetail, type EvidenceVerdict, type GovernanceResult } from '../../api/cases'
import { useAuthStore } from '../../auth/store'

import { DecisionForm } from './components/DecisionForm'
import { JsonBlock, KeyValue, MutedNarrative, StagePanel } from './components/StagePanel'
import { StatusPill } from './components/StatusPill'

// Per chunk 5.5 plan: full case detail view. Renders every stage row
// the pipeline produced (evidence, portfolio risk, synthesis, IC1,
// governance, A1, decision artifact, plus diagnostic-mode HealthReport
// or briefing-mode BriefingNote).
//
// CIO sees the DecisionForm if the case is awaiting_decision.

export function CaseDetailPage() {
  const params = useParams({ strict: false }) as { caseId?: string }
  const caseId = params.caseId
  const { data, isLoading, error } = useCaseDetail(caseId)
  const role = useAuthStore((s) => s.user?.role)

  if (isLoading) return <p className="p-8 text-sm text-gray-500">Loading case…</p>
  if (error)
    return (
      <p className="p-8 text-sm text-red-600">
        Could not load case: {error instanceof Error ? error.message : 'unknown'}
      </p>
    )
  if (!data) return null

  const { case: c, evidence_verdicts, portfolio_risk_analytics, synthesis, ic1_deliberation, governance_results, a1_challenge, decision_artifact, briefing_note, health_report } = data

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <header>
        <div className="flex items-center gap-3">
          <Link
            to="/cases"
            className="text-sm text-blue-600 hover:underline"
          >
            ← All cases
          </Link>
          <StatusPill status={c.status} />
        </div>
        <h1 className="mt-3 text-2xl font-semibold text-gray-900">
          {c.case_mode.replace('_', ' ').replace(/\b\w/g, (m) => m.toUpperCase())} —{' '}
          {c.case_intent?.replace(/_/g, ' ') ?? 'no intent'}
        </h1>
        <p className="text-xs font-mono text-gray-500">{c.case_id}</p>
        {c.proposed_action && (
          <p className="mt-3 rounded bg-blue-50 px-3 py-2 text-sm text-blue-900">
            <span className="font-medium">Proposed action:</span> {c.proposed_action}
          </p>
        )}
      </header>

      {/* Case overview */}
      <StagePanel title="Case Overview">
        <KeyValue label="Investor" value={<span className="font-mono text-xs">{c.investor_id}</span>} />
        <KeyValue label="Opened by" value={c.opened_by} />
        <KeyValue label="Assigned to" value={c.assigned_to} />
        <KeyValue label="Created via" value={c.created_via} />
        <KeyValue label="Created at" value={new Date(c.created_at).toLocaleString()} />
        {c.snapshot_bundle_id && (
          <KeyValue
            label="Snapshot bundle"
            value={<span className="font-mono text-xs">{c.snapshot_bundle_id}</span>}
          />
        )}
        {c.proposed_action_amount_inr && (
          <KeyValue
            label="Proposed amount"
            value={`₹${Number(c.proposed_action_amount_inr).toLocaleString('en-IN')}`}
          />
        )}
        {c.proposed_action_products.length > 0 && (
          <KeyValue label="Products" value={c.proposed_action_products.join(', ')} />
        )}
        {c.is_material !== null && (
          <KeyValue
            label="Material?"
            value={
              <span className={c.is_material ? 'text-amber-700' : 'text-gray-700'}>
                {c.is_material ? 'Yes' : 'No'}
                {c.materiality_reason && (
                  <span className="ml-2 font-mono text-xs text-gray-500">
                    ({c.materiality_reason})
                  </span>
                )}
              </span>
            }
          />
        )}
      </StagePanel>

      {/* Evidence */}
      {evidence_verdicts.length > 0 && (
        <StagePanel
          title="Evidence Verdicts"
          subtitle={`${evidence_verdicts.length} agent${evidence_verdicts.length === 1 ? '' : 's'} contributed`}
        >
          <div className="space-y-3">
            {evidence_verdicts.map((v) => (
              <EvidenceRow key={v.verdict_id} verdict={v} />
            ))}
          </div>
        </StagePanel>
      )}

      {/* Portfolio risk */}
      {portfolio_risk_analytics && (
        <StagePanel
          title="Portfolio Risk Analytics"
          badge={
            portfolio_risk_analytics.overall_risk_level && (
              <RiskBadge level={portfolio_risk_analytics.overall_risk_level} />
            )
          }
        >
          <MutedNarrative text={portfolio_risk_analytics.reasoning_summary} />
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-900">
              Detailed assessments
            </summary>
            <div className="mt-2 space-y-2">
              <JsonBlock value={portfolio_risk_analytics.concentration_assessment} />
              <JsonBlock value={portfolio_risk_analytics.liquidity_assessment} />
            </div>
          </details>
        </StagePanel>
      )}

      {/* Synthesis */}
      {synthesis && (
        <StagePanel
          title="Synthesis"
          subtitle={synthesis.output_mode}
          badge={
            synthesis.recommendation && (
              <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-900">
                {synthesis.recommendation}
              </span>
            )
          }
        >
          <MutedNarrative text={synthesis.synthesis_narrative} />
          {synthesis.amplification && (
            <div className="mt-3 rounded bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <span className="font-medium">Amplification flag:</span>{' '}
              {JSON.stringify(synthesis.amplification)}
            </div>
          )}
        </StagePanel>
      )}

      {/* IC1 (only material proposed_action / scenario) */}
      {ic1_deliberation && (
        <StagePanel
          title="IC1 Deliberation"
          badge={
            <span className="rounded bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-900">
              {ic1_deliberation.recommendation}
            </span>
          }
        >
          <MutedNarrative text={ic1_deliberation.chair_summary} />
          {ic1_deliberation.devils_advocate_position && (
            <div className="mt-3 rounded bg-rose-50 px-3 py-2 text-sm text-rose-900">
              <span className="font-medium">Devil's advocate:</span>{' '}
              {ic1_deliberation.devils_advocate_position}
            </div>
          )}
        </StagePanel>
      )}

      {/* Governance gates */}
      {governance_results.length > 0 && (
        <StagePanel
          title="Governance Gates"
          subtitle={`${governance_results.length} of 3 ran`}
        >
          <div className="space-y-2">
            {governance_results.map((g) => (
              <GovernanceRow key={g.result_id} result={g} />
            ))}
          </div>
        </StagePanel>
      )}

      {/* A1 challenge */}
      {a1_challenge && (
        <StagePanel
          title="A1 Challenge"
          subtitle="Adversarial counter-arguments + alternatives"
        >
          {a1_challenge.counter_arguments && (
            <div>
              <h4 className="mb-1 text-xs font-medium text-gray-600">
                Counter-arguments
              </h4>
              <JsonBlock value={a1_challenge.counter_arguments} />
            </div>
          )}
          {a1_challenge.alternative_proposals && (
            <div className="mt-3">
              <h4 className="mb-1 text-xs font-medium text-gray-600">
                Alternative proposals
              </h4>
              <JsonBlock value={a1_challenge.alternative_proposals} />
            </div>
          )}
        </StagePanel>
      )}

      {/* Briefing / health */}
      {briefing_note && (
        <StagePanel title="Briefing Note" subtitle="briefing-mode output">
          <MutedNarrative text={briefing_note.meeting_context} />
          {briefing_note.prep_questions && (
            <div className="mt-3">
              <h4 className="mb-1 text-xs font-medium text-gray-600">
                Prep questions
              </h4>
              <JsonBlock value={briefing_note.prep_questions} />
            </div>
          )}
        </StagePanel>
      )}

      {health_report && (
        <StagePanel
          title="Health Report"
          subtitle="diagnostic-mode output"
          badge={<HealthBadge health={health_report.overall_health} />}
        >
          <KeyValue label="Asset allocation" value={<JsonBlock value={health_report.asset_allocation_status} />} />
          <KeyValue label="Performance" value={<JsonBlock value={health_report.performance_summary} />} />
        </StagePanel>
      )}

      {/* Decision artifact / form */}
      {decision_artifact ? (
        <StagePanel
          title="Decision"
          badge={
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                decision_artifact.decision === 'approved'
                  ? 'bg-emerald-100 text-emerald-800'
                  : decision_artifact.decision === 'rejected'
                  ? 'bg-rose-100 text-rose-800'
                  : 'bg-amber-100 text-amber-800'
              }`}
            >
              {decision_artifact.decision}
            </span>
          }
        >
          <p className="text-sm font-medium text-gray-900">Rationale</p>
          <p className="mt-1 leading-relaxed text-gray-700">{decision_artifact.rationale}</p>
          <KeyValue label="Decided by" value={decision_artifact.decided_by} />
          <KeyValue
            label="Decided at"
            value={new Date(decision_artifact.decided_at).toLocaleString()}
          />
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-900">
              Audit hashes
            </summary>
            <div className="mt-2 space-y-1 font-mono text-xs text-gray-600">
              <KeyValue
                label="evidence_packet_hash"
                value={shorten(decision_artifact.evidence_packet_hash)}
              />
              <KeyValue
                label="synthesis_hash"
                value={shorten(decision_artifact.synthesis_hash)}
              />
              <KeyValue
                label="governance_packet_hash"
                value={shorten(decision_artifact.governance_packet_hash)}
              />
              {decision_artifact.portfolio_risk_hash && (
                <KeyValue
                  label="portfolio_risk_hash"
                  value={shorten(decision_artifact.portfolio_risk_hash)}
                />
              )}
              {decision_artifact.ic1_hash && (
                <KeyValue label="ic1_hash" value={shorten(decision_artifact.ic1_hash)} />
              )}
              {decision_artifact.a1_hash && (
                <KeyValue label="a1_hash" value={shorten(decision_artifact.a1_hash)} />
              )}
            </div>
          </details>
        </StagePanel>
      ) : (
        c.status === 'awaiting_decision' &&
        role === 'cio' && <DecisionForm caseId={c.case_id} />
      )}

      {!decision_artifact && c.status === 'awaiting_decision' && role !== 'cio' && (
        <div className="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Awaiting CIO decision. Recording is restricted to the CIO role
          per FR 20.4 §7.1.
        </div>
      )}
    </div>
  )
}

function shorten(hash: string): string {
  return `${hash.slice(0, 12)}…${hash.slice(-8)}`
}

function EvidenceRow({ verdict }: { verdict: EvidenceVerdict }) {
  const conf = verdict.confidence ? `${(parseFloat(verdict.confidence) * 100).toFixed(0)}%` : '—'
  return (
    <div className="rounded border border-gray-100 bg-gray-50 px-3 py-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-900">
          {verdict.agent_id.replace('e1_', '').replace('_evidence', '')}
        </span>
        <div className="flex items-center gap-2 text-xs">
          {verdict.risk_level && <RiskBadge level={verdict.risk_level} />}
          <span className="text-gray-500">{conf}</span>
        </div>
      </div>
      {verdict.structured_output &&
        typeof verdict.structured_output === 'object' &&
        'verdict_summary' in verdict.structured_output && (
          <p className="mt-1 text-xs text-gray-600">
            {String(
              (verdict.structured_output as { verdict_summary: unknown })
                .verdict_summary,
            )}
          </p>
        )}
    </div>
  )
}

function GovernanceRow({ result }: { result: GovernanceResult }) {
  const colour =
    result.outcome === 'approved'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
      : result.outcome === 'blocked'
      ? 'border-rose-200 bg-rose-50 text-rose-900'
      : 'border-amber-200 bg-amber-50 text-amber-900'
  return (
    <div className={`rounded border ${colour} px-3 py-2 text-sm`}>
      <div className="flex items-center justify-between">
        <span className="font-medium">{result.gate}</span>
        <span className="text-xs uppercase">{result.outcome}</span>
      </div>
      {result.reasoning && <p className="mt-1 text-xs">{result.reasoning}</p>}
    </div>
  )
}

function RiskBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    low: 'bg-emerald-100 text-emerald-800',
    medium: 'bg-amber-100 text-amber-800',
    high: 'bg-orange-100 text-orange-800',
    critical: 'bg-rose-100 text-rose-800',
  }
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${map[level] ?? 'bg-gray-100 text-gray-700'}`}>
      {level}
    </span>
  )
}

function HealthBadge({ health }: { health: string }) {
  const map: Record<string, string> = {
    healthy: 'bg-emerald-100 text-emerald-800',
    attention_needed: 'bg-amber-100 text-amber-800',
    urgent: 'bg-rose-100 text-rose-800',
  }
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${map[health] ?? 'bg-gray-100'}`}>
      {health.replace('_', ' ')}
    </span>
  )
}
