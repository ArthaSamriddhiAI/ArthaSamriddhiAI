import { Link } from '@tanstack/react-router'
import { ArrowLeft, Camera, CheckCircle2, Loader2, ShieldCheck, XCircle } from 'lucide-react'
import { useState } from 'react'

import {
  type SnapshotSummary,
  useCreateSnapshot,
  useSnapshots,
  useVerifySnapshot,
} from '../../api/admin'
import { useAuthStore } from '../../auth/store'
import { cn } from '../../lib/cn'

// Cluster 3 chunk 3.4 — snapshot list + create + verify.

export function SnapshotsPage() {
  const role = useAuthStore((s) => s.user?.role)
  const canWrite = role === 'audit'
  const { data, isLoading, error } = useSnapshots()
  const createMutation = useCreateSnapshot()
  const [draftDescription, setDraftDescription] = useState('')

  const onCreate = () => {
    createMutation.mutate(
      { description: draftDescription || undefined },
      {
        onSuccess: () => setDraftDescription(''),
      },
    )
  }

  return (
    <div className="p-8 max-w-5xl">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to admin
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">Snapshots</h1>
      <p className="text-sm text-gray-600 mb-6">
        Point-in-time captures of every canonical entity. Each snapshot
        carries a SHA-256 hash of the canonical-JSON-encoded payload;
        verification re-encodes and compares.
      </p>

      {canWrite && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm mb-6">
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Optional description"
              value={draftDescription}
              onChange={(e) => setDraftDescription(e.target.value)}
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1"
            />
            <button
              type="button"
              onClick={onCreate}
              disabled={createMutation.isPending}
              className={cn(
                'inline-flex items-center gap-1 rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
              style={{ backgroundColor: 'var(--color-primary)' }}
            >
              <Camera size={14} />
              {createMutation.isPending ? 'Creating…' : 'Create Snapshot'}
            </button>
          </div>
          {createMutation.error && (
            <div className="mt-2 text-xs text-red-700">
              {createMutation.error.message}
            </div>
          )}
        </div>
      )}

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

      {data && data.snapshots.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
          No snapshots yet.
        </div>
      )}

      {data && data.snapshots.length > 0 && (
        <div className="space-y-3">
          {data.snapshots.map((s) => (
            <SnapshotRow key={s.snapshot_id} snapshot={s} canWrite={canWrite} />
          ))}
        </div>
      )}
    </div>
  )
}

function SnapshotRow({
  snapshot,
  canWrite,
}: {
  snapshot: SnapshotSummary
  canWrite: boolean
}) {
  const verifyMutation = useVerifySnapshot()
  const [verifyResult, setVerifyResult] = useState<string | null>(null)

  const onVerify = () => {
    setVerifyResult(null)
    verifyMutation.mutate(snapshot.snapshot_id, {
      onSuccess: (result) => {
        setVerifyResult(
          result.verified_status === 'verified'
            ? `verified (${result.stored_hash.slice(0, 16)}…)`
            : `verification_failed (stored=${result.stored_hash.slice(
                0,
                16,
              )}…, computed=${result.recomputed_hash.slice(0, 16)}…)`,
        )
      },
      onError: (err) => setVerifyResult(`failed: ${err.message}`),
    })
  }

  const totalEntities = Object.values(snapshot.entity_counts).reduce(
    (s, n) => s + n,
    0,
  )

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <code className="text-xs text-gray-500">{snapshot.snapshot_id}</code>
            <StatusBadge status={snapshot.verified_status} />
          </div>
          {snapshot.description && (
            <div className="text-sm text-gray-900 mb-1">
              {snapshot.description}
            </div>
          )}
          <div className="text-xs text-gray-500">
            Created{' '}
            {new Date(snapshot.created_at).toLocaleString()} by{' '}
            <span className="font-mono">{snapshot.created_by}</span> ·{' '}
            {totalEntities} entities ·{' '}
            {(snapshot.serialised_payload_size_bytes / 1024).toFixed(1)} KB
            · trigger: {snapshot.trigger_type}
          </div>
          <div className="text-xs text-gray-500 mt-1 font-mono">
            hash {snapshot.content_hash.slice(0, 24)}…
          </div>
          {verifyResult && (
            <div className="text-xs text-gray-700 mt-2">{verifyResult}</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onVerify}
            disabled={!canWrite || verifyMutation.isPending}
            className={cn(
              'inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700',
              'hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50',
            )}
            title={canWrite ? 'Re-hash and compare' : 'Audit role required'}
          >
            <ShieldCheck size={12} /> Verify
          </button>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: SnapshotSummary['verified_status'] }) {
  if (status === 'verified') {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-800">
        <CheckCircle2 size={12} /> verified
      </span>
    )
  }
  if (status === 'verification_failed') {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-800">
        <XCircle size={12} /> failed
      </span>
    )
  }
  return (
    <span className="inline-block rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-700">
      never verified
    </span>
  )
}
