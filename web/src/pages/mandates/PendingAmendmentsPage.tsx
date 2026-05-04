import { Link } from '@tanstack/react-router'
import { ArrowRight, Inbox, Loader2 } from 'lucide-react'

import { usePendingAmendments } from '../../api/mandates'

// Per chunk plan §2.3 §scope_in:
//   "CIO pending amendments queue UI at /app/cio/pending-amendments:
//    lists pending amendments with summary; row click opens review surface."

export function PendingAmendmentsPage() {
  const queue = usePendingAmendments()

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">
        Pending Amendments
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Review proposed mandate amendments. Click a row to open the
        side-by-side diff and impact analysis.
      </p>

      {queue.isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={14} className="animate-spin" />
          Loading queue…
        </div>
      )}

      {queue.error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load pending amendments.
        </div>
      )}

      {queue.data && queue.data.length === 0 && (
        <div className="rounded-md border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
          <Inbox size={20} className="mx-auto mb-2 text-gray-400" />
          No amendments awaiting your review.
        </div>
      )}

      {queue.data && queue.data.length > 0 && (
        <div className="space-y-3">
          {queue.data.map((row) => (
            <Link
              key={row.version_id}
              to="/pending-amendments/$versionId"
              params={{ versionId: row.version_id }}
              className="block rounded-lg border border-gray-200 bg-white px-5 py-4 shadow-sm hover:border-gray-300 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    {row.investor_name}
                    <span className="ml-2 font-mono text-xs text-gray-500">
                      {row.investor_pan}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    Version {row.version_number} · proposed by{' '}
                    {row.proposed_by ?? '—'}
                    {row.proposed_at
                      ? ` · ${new Date(row.proposed_at).toLocaleString()}`
                      : ''}
                  </div>
                  <ul className="mt-2 list-disc list-inside text-xs text-gray-700">
                    {row.change_summary.map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                  </ul>
                </div>
                <ArrowRight size={16} className="text-gray-400" />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
