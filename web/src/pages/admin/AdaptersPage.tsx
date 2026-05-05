import { Link } from '@tanstack/react-router'
import { ArrowLeft, CheckCircle2, Loader2, Play, XCircle } from 'lucide-react'
import { useState } from 'react'

import { useAdapters, useRunAdapter } from '../../api/admin'
import { useAuthStore } from '../../auth/store'
import { cn } from '../../lib/cn'

// Cluster 3 chunk 3.4 — adapter list with run capability.

export function AdaptersPage() {
  const { data, isLoading, error } = useAdapters()
  const role = useAuthStore((s) => s.user?.role)
  const canRun = role === 'audit'

  return (
    <div className="p-8 max-w-5xl">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to admin
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">Adapters</h1>
      <p className="text-sm text-gray-600 mb-6">
        Registered D0 adapters and their health status. Click <em>Run</em>
        to fetch new data, or <em>Validate</em> to dry-run schema checks
        without writing canonical entities.
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

      {data && data.adapters.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
          No adapters registered.
        </div>
      )}

      {data && data.adapters.length > 0 && (
        <div className="space-y-3">
          {data.adapters.map((a) => (
            <AdapterRow key={a.source_identifier} adapter={a} canRun={canRun} />
          ))}
        </div>
      )}
    </div>
  )
}

function AdapterRow({
  adapter,
  canRun,
}: {
  adapter: ReturnType<typeof useAdapters>['data'] extends infer T
    ? T extends { adapters: Array<infer A> }
      ? A
      : never
    : never
  canRun: boolean
}) {
  const runMutation = useRunAdapter(adapter.source_identifier)
  const [lastResult, setLastResult] = useState<string | null>(null)

  const onRun = (mode: 'full' | 'validation') => {
    setLastResult(null)
    runMutation.mutate(
      { mode },
      {
        onSuccess: (result) => {
          const created = Object.entries(result.canonical_entities_created)
            .map(([k, v]) => `${k}: +${v}`)
            .join(', ')
          const updated = Object.entries(result.canonical_entities_updated)
            .map(([k, v]) => `${k}: ~${v}`)
            .join(', ')
          const detail = [created, updated].filter(Boolean).join(' / ')
          setLastResult(
            `${result.status} (${detail || 'no entity changes'}, errors=${result.error_count})`,
          )
        },
        onError: (err) => {
          setLastResult(`failed: ${err.message}`)
        },
      },
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <code className="text-sm font-medium text-gray-900">
              {adapter.source_identifier}
            </code>
            {adapter.healthy ? (
              <span className="inline-flex items-center gap-1 rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-800">
                <CheckCircle2 size={12} /> healthy
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-800">
                <XCircle size={12} /> unhealthy
              </span>
            )}
          </div>
          <div className="text-xs text-gray-500 mb-1">
            Entities:&nbsp;
            <span className="font-mono">
              {adapter.supported_entity_types.join(', ')}
            </span>
          </div>
          {adapter.last_successful_fetch_at && (
            <div className="text-xs text-gray-500">
              Last fetch:{' '}
              {new Date(adapter.last_successful_fetch_at).toLocaleString()}
            </div>
          )}
          {adapter.last_error_message && (
            <div className="text-xs text-red-700 mt-1">
              {adapter.last_error_message}
            </div>
          )}
          {lastResult && (
            <div className="text-xs text-gray-700 mt-2">{lastResult}</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onRun('validation')}
            disabled={!canRun || runMutation.isPending}
            className={cn(
              'rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700',
              'hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50',
            )}
            title={canRun ? 'Validate without writing' : 'Audit role required'}
          >
            Validate
          </button>
          <button
            type="button"
            onClick={() => onRun('full')}
            disabled={!canRun || runMutation.isPending}
            className={cn(
              'inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium text-white shadow-sm',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
            style={{ backgroundColor: 'var(--color-primary)' }}
            title={canRun ? 'Run + write canonical entities' : 'Audit role required'}
          >
            <Play size={12} /> Run
          </button>
        </div>
      </div>
    </div>
  )
}
