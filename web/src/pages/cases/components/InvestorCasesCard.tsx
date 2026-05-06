import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'

import { useCasesList } from '../../../api/cases'

import { StatusPill } from './StatusPill'

interface Props {
  investorId: string
}

// Embedded on the investor detail page (chunk 5.5 §5.5.4): shows the
// last few cases for this investor + an "Open New Case" CTA.

export function InvestorCasesCard({ investorId }: Props) {
  const { data } = useCasesList({ investor_id: investorId, limit: 5 })

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Cases</h3>
          <p className="text-xs text-gray-500">
            {data ? `${data.total} total` : 'Loading…'}
          </p>
        </div>
        <Link
          to="/cases/new"
          search={{ investorId }}
          className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-opacity hover:opacity-90"
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          <Plus size={14} />
          New Case
        </Link>
      </div>

      {data && data.cases.length === 0 && (
        <p className="text-sm text-gray-500">
          No cases for this investor yet. Open one to start the reasoning
          pipeline.
        </p>
      )}

      {data && data.cases.length > 0 && (
        <ul className="space-y-2">
          {data.cases.map((c) => (
            <li
              key={c.case_id}
              className="flex items-center justify-between gap-3 rounded border border-gray-100 bg-gray-50 px-3 py-2 text-sm"
            >
              <Link
                to="/cases/$caseId"
                params={{ caseId: c.case_id }}
                className="font-mono text-xs text-blue-600 hover:underline"
              >
                {c.case_id.slice(0, 8)}…
              </Link>
              <span className="text-gray-700">{c.case_mode.replace('_', ' ')}</span>
              <span className="text-gray-500">{c.case_intent ?? '—'}</span>
              <StatusPill status={c.status} />
              <span className="text-xs text-gray-400">
                {new Date(c.created_at).toLocaleDateString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
