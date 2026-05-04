import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { ArrowLeft, CheckCircle2, Loader2, MessageSquareWarning, XCircle } from 'lucide-react'
import { useState } from 'react'

import {
  type AmendmentDiff,
  useAmendmentDiff,
  useApproveAmendment,
  useRejectAmendment,
  useRequestChangesAmendment,
} from '../../api/mandates'
import { cn } from '../../lib/cn'

import { MandateSummaryCard } from './components/MandateSummaryCard'

// Per chunk plan §2.3 §scope_in:
//   "Amendment review surface at /app/cio/pending-amendments/{version_id}:
//     - Side-by-side diff view (current active on left, proposed on right)
//       with change highlighting per FR Entry 12.2 §4.2.
//     - Plain-language change summary at top.
//     - Impact analysis section with three subsections: structural diff
//       (always populated), portfolio implications panel (cluster 4
//       placeholder), activation summary.
//     - Three-action buttons (Approve, Request Changes, Reject) with
//       appropriate comment field requirements."

type ActionMode = 'approve' | 'reject' | 'request_changes' | null


export function AmendmentReviewPage() {
  const { versionId } = useParams({ strict: false }) as { versionId: string }
  const navigate = useNavigate()
  const diffQuery = useAmendmentDiff(versionId)
  const approveMutation = useApproveAmendment(versionId)
  const rejectMutation = useRejectAmendment(versionId)
  const requestChangesMutation = useRequestChangesAmendment(versionId)
  const [actionMode, setActionMode] = useState<ActionMode>(null)
  const [comments, setComments] = useState('')

  if (diffQuery.isLoading) {
    return (
      <div className="p-8 max-w-6xl flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin" /> Loading diff…
      </div>
    )
  }

  if (diffQuery.error || !diffQuery.data) {
    return (
      <div className="p-8 max-w-6xl">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {diffQuery.error instanceof Error
            ? diffQuery.error.message
            : 'Failed to load amendment.'}
        </div>
      </div>
    )
  }

  const diff = diffQuery.data
  const modifiedFields = computeModifiedFields(diff)

  const handleApprove = () => {
    approveMutation.mutate(
      { comments: comments || undefined },
      {
        onSuccess: () => {
          navigate({ to: '/pending-amendments' })
        },
      },
    )
  }
  const handleReject = () => {
    rejectMutation.mutate(
      { rejection_reason: comments },
      {
        onSuccess: () => {
          navigate({ to: '/pending-amendments' })
        },
      },
    )
  }
  const handleRequestChanges = () => {
    requestChangesMutation.mutate(
      { comments },
      {
        onSuccess: () => {
          navigate({ to: '/pending-amendments' })
        },
      },
    )
  }

  return (
    <div className="p-8 max-w-6xl">
      <Link
        to="/pending-amendments"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to queue
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-1">
        Amendment Review
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Compare the active mandate to the proposed amendment. Approve activates
        version {diff.proposed.version_number} and archives the current active
        version.
      </p>

      {/* Plain-language summary */}
      <section className="mb-6 rounded-lg border border-blue-200 bg-blue-50 p-4">
        <h2 className="text-sm font-semibold text-blue-900 mb-2">
          Changes proposed
        </h2>
        <ul className="list-disc list-inside text-sm text-blue-900">
          {diff.summary.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      </section>

      {/* Side-by-side diff */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <MandateSummaryCard
          title={`Version ${diff.active.version_number} — active`}
          version={diff.active}
        />
        <MandateSummaryCard
          title={`Version ${diff.proposed.version_number} — proposed`}
          version={diff.proposed}
          highlightFields={modifiedFields}
        />
      </div>

      {/* Impact analysis */}
      <section className="mb-6 rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">
          Impact analysis
        </h2>

        <div className="mb-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Structural changes
          </h3>
          {diff.impact.structural.length === 0 ? (
            <div className="text-xs text-gray-500">No structural changes.</div>
          ) : (
            <ul className="space-y-2 text-sm text-gray-700">
              {diff.impact.structural.map((s, i) => (
                <li key={i}>
                  <span className="font-medium">{s.label}</span>
                  <div className="text-xs text-gray-500">{s.explanation}</div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mb-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Portfolio implications
          </h3>
          <div
            className={cn(
              'rounded-md border border-dashed px-4 py-3 text-xs',
              diff.impact.portfolio_implications.status === 'cluster_4_placeholder'
                ? 'border-gray-300 bg-gray-50 text-gray-600'
                : 'border-blue-200 bg-blue-50 text-blue-900',
            )}
          >
            {diff.impact.portfolio_implications.message}
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Activation summary
          </h3>
          <div className="text-xs text-gray-700">
            {diff.impact.activation_summary}
          </div>
        </div>
      </section>

      {/* Three-action panel */}
      <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        {actionMode === null ? (
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => {
                setActionMode('approve')
                setComments('')
              }}
              className="inline-flex items-center gap-1.5 rounded-md px-5 py-2 text-sm font-medium text-white shadow-sm"
              style={{ backgroundColor: 'var(--color-primary)' }}
            >
              <CheckCircle2 size={14} />
              Approve
            </button>
            <button
              type="button"
              onClick={() => {
                setActionMode('request_changes')
                setComments('')
              }}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-white',
                'px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-50',
              )}
            >
              <MessageSquareWarning size={14} />
              Request Changes
            </button>
            <button
              type="button"
              onClick={() => {
                setActionMode('reject')
                setComments('')
              }}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-white',
                'px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50',
              )}
            >
              <XCircle size={14} />
              Reject
            </button>
          </div>
        ) : (
          <ActionForm
            mode={actionMode}
            comments={comments}
            setComments={setComments}
            isPending={
              approveMutation.isPending
              || rejectMutation.isPending
              || requestChangesMutation.isPending
            }
            error={
              (actionMode === 'approve' && approveMutation.error)
              || (actionMode === 'reject' && rejectMutation.error)
              || (actionMode === 'request_changes' && requestChangesMutation.error)
              || null
            }
            onCancel={() => {
              setActionMode(null)
              setComments('')
            }}
            onConfirm={() => {
              if (actionMode === 'approve') handleApprove()
              else if (actionMode === 'reject') handleReject()
              else if (actionMode === 'request_changes') handleRequestChanges()
            }}
          />
        )}
      </section>
    </div>
  )
}


function ActionForm({
  mode,
  comments,
  setComments,
  isPending,
  error,
  onCancel,
  onConfirm,
}: {
  mode: Exclude<ActionMode, null>
  comments: string
  setComments: (next: string) => void
  isPending: boolean
  error: Error | null
  onCancel: () => void
  onConfirm: () => void
}) {
  const config = {
    approve: {
      heading: 'Approve amendment',
      hint: 'Comments are optional but appear in the audit trail.',
      placeholder: 'Optional approval comment…',
      required: false,
      buttonText: 'Confirm approval',
      buttonClass: 'text-white',
      buttonStyle: { backgroundColor: 'var(--color-primary)' },
    },
    reject: {
      heading: 'Reject amendment',
      hint: 'A rejection reason is required and visible to the advisor.',
      placeholder: 'Why are you rejecting this amendment?',
      required: true,
      buttonText: 'Confirm rejection',
      buttonClass: 'bg-red-600 text-white hover:bg-red-700',
      buttonStyle: undefined,
    },
    request_changes: {
      heading: 'Request changes',
      hint: 'Tell the advisor what needs to change. The amendment returns to draft.',
      placeholder: 'What needs to change?',
      required: true,
      buttonText: 'Send back to advisor',
      buttonClass: 'bg-amber-600 text-white hover:bg-amber-700',
      buttonStyle: undefined,
    },
  }[mode]

  const disabled = isPending || (config.required && !comments.trim())

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-900 mb-1">
        {config.heading}
      </h3>
      <p className="text-xs text-gray-500 mb-3">{config.hint}</p>
      <textarea
        value={comments}
        onChange={(e) => setComments(e.target.value)}
        placeholder={config.placeholder}
        rows={4}
        className={cn(
          'w-full rounded-md border border-gray-300 px-3 py-2 text-sm',
          'focus:outline-none focus:ring-2 focus:ring-offset-1',
        )}
      />
      {error && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error.message}
        </div>
      )}
      <div className="mt-4 flex gap-3">
        <button
          type="button"
          onClick={onConfirm}
          disabled={disabled}
          className={cn(
            'rounded-md px-5 py-2 text-sm font-medium shadow-sm',
            'disabled:cursor-not-allowed disabled:opacity-50',
            config.buttonClass,
          )}
          style={config.buttonStyle}
        >
          {isPending ? 'Working…' : config.buttonText}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}


function computeModifiedFields(diff: AmendmentDiff): Set<string> {
  const fields = new Set<string>()
  for (const change of diff.numeric_changes) {
    fields.add(change.field)
  }
  for (const item of diff.prohibited_change.added) {
    fields.add(`prohibited:${item}`)
  }
  for (const item of diff.prohibited_change.removed) {
    fields.add(`prohibited:${item}`)
  }
  return fields
}
