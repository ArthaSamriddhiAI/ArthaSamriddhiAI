import { Link } from '@tanstack/react-router'
import { ArrowLeft, Loader2 } from 'lucide-react'

import { useFreshness } from '../../api/admin'
import { cn } from '../../lib/cn'

// Cluster 3 chunk 3.4 — freshness dashboard (FR 10.5 §4.1).

const STATUS_STYLES: Record<string, string> = {
  fresh: 'bg-green-100 text-green-800 ring-1 ring-green-300',
  stale: 'bg-yellow-100 text-yellow-900 ring-1 ring-yellow-300',
  very_stale: 'bg-red-100 text-red-800 ring-1 ring-red-300',
}

function formatAge(seconds: number): string {
  if (seconds >= 86400) {
    const days = Math.floor(seconds / 86400)
    return `${days} day${days !== 1 ? 's' : ''}`
  }
  if (seconds >= 3600) {
    const h = Math.floor(seconds / 3600)
    return `${h} hour${h !== 1 ? 's' : ''}`
  }
  const m = Math.max(1, Math.floor(seconds / 60))
  return `${m} min`
}

export function FreshnessPage() {
  const { data, isLoading, error } = useFreshness()

  return (
    <div className="p-8 max-w-5xl">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to admin
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">
        Data Freshness
      </h1>
      <p className="text-sm text-gray-600 mb-6">
        Each canonical-entity table's freshness against its threshold. A
        stale table means the latest record is older than the threshold;
        very-stale means double the threshold. Tables with no rows show as
        very-stale by convention.
      </p>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      )}

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error.message}
        </div>
      )}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-4 py-2 text-left">Entity Table</th>
                <th className="px-4 py-2 text-right">Records</th>
                <th className="px-4 py-2 text-left">Latest Modified</th>
                <th className="px-4 py-2 text-right">Age</th>
                <th className="px-4 py-2 text-right">Threshold</th>
                <th className="px-4 py-2 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.rows.map((row) => (
                <tr key={row.entity_table}>
                  <td className="px-4 py-2 font-mono text-gray-900">
                    {row.entity_table}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-700">
                    {row.record_count}
                  </td>
                  <td className="px-4 py-2 text-gray-700">
                    {row.latest_last_modified_at
                      ? new Date(
                          row.latest_last_modified_at,
                        ).toLocaleString()
                      : '—'}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-700">
                    {row.record_count === 0
                      ? '—'
                      : formatAge(row.age_seconds)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-500">
                    {row.threshold_human}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <span
                      className={cn(
                        'inline-block rounded px-2 py-0.5 text-xs font-medium',
                        STATUS_STYLES[row.freshness_status] ??
                          'bg-gray-100 text-gray-700',
                      )}
                    >
                      {row.freshness_status.replace('_', ' ')}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
