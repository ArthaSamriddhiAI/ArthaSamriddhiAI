import type { CaseStatus } from '../../../api/cases'
import { formatStatus } from '../../../api/cases'

interface Props {
  status: CaseStatus
}

const STATUS_COLORS: Record<CaseStatus, string> = {
  opening: 'bg-gray-100 text-gray-700',
  gathering_evidence: 'bg-blue-50 text-blue-700',
  synthesizing: 'bg-blue-100 text-blue-800',
  awaiting_committee: 'bg-purple-100 text-purple-800',
  awaiting_governance: 'bg-amber-100 text-amber-800',
  awaiting_challenge: 'bg-orange-100 text-orange-800',
  awaiting_decision: 'bg-yellow-100 text-yellow-900',
  decided: 'bg-emerald-100 text-emerald-800',
  archived: 'bg-gray-100 text-gray-600',
  failed: 'bg-rose-100 text-rose-800',
}

export function StatusPill({ status }: Props) {
  const cls = STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-700'
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}
    >
      {formatStatus(status)}
    </span>
  )
}
