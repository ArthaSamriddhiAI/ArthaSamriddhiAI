import { Link } from '@tanstack/react-router'
import { ArrowLeft, Loader2 } from 'lucide-react'

import { useStagingRecords } from '../../api/admin'

export function StagingPage() {
  const { data, isLoading, error } = useStagingRecords({ limit: 100 })

  return (
    <div className="p-8 max-w-6xl">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to admin
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">
        Staging Records
      </h1>
      <p className="text-sm text-gray-600 mb-6">
        Raw fetches preserved with content-hashes for audit replay. Each
        record is the unmodified source payload for one adapter run.
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

      {data && data.records.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
          No staging records yet. Run an adapter to populate.
        </div>
      )}

      {data && data.records.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-4 py-2 text-left">Source</th>
                <th className="px-4 py-2 text-left">Subkey</th>
                <th className="px-4 py-2 text-left">Run ID</th>
                <th className="px-4 py-2 text-left">Hash</th>
                <th className="px-4 py-2 text-right">Size</th>
                <th className="px-4 py-2 text-left">Fetched</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.records.map((r) => (
                <tr key={r.staging_record_id}>
                  <td className="px-4 py-2 font-mono text-xs text-gray-900">
                    {r.source_identifier}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {r.source_subkey || '—'}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-500">
                    {r.adapter_run_id.slice(0, 8)}…
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-500">
                    {r.raw_content_hash.slice(0, 12)}…
                  </td>
                  <td className="px-4 py-2 text-right text-gray-700">
                    {(r.raw_content_size_bytes / 1024).toFixed(1)} KB
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {new Date(r.fetched_at).toLocaleString()}
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
