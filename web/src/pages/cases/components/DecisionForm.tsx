import { useState } from 'react'

import {
  useRecordDecision,
  type DecisionRecordPayload,
  type DecisionVerdict,
} from '../../../api/cases'

interface Props {
  caseId: string
}

const VERDICT_OPTIONS: Array<{ value: DecisionVerdict; label: string; helper: string }> = [
  { value: 'approved', label: 'Approve', helper: 'Proceed with the action as proposed.' },
  { value: 'modified', label: 'Approve with Modifications', helper: 'Reduce size, change timing, etc.' },
  { value: 'rejected', label: 'Reject', helper: 'Do not proceed.' },
  { value: 'deferred', label: 'Defer', helper: 'Postpone — re-open or revisit later.' },
]

// CIO-only form. The route guard already gates access, but the form
// surfaces a clear "you can't decide on this case" message if the
// permissions don't match (e.g. CIO opens the page but the case is
// not awaiting_decision).

export function DecisionForm({ caseId }: Props) {
  const [verdict, setVerdict] = useState<DecisionVerdict>('approved')
  const [rationale, setRationale] = useState('')
  const [modifications, setModifications] = useState('')
  const [conditions, setConditions] = useState('')

  const mutation = useRecordDecision(caseId)

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (rationale.trim().length === 0) return
    const payload: DecisionRecordPayload = {
      decision: verdict,
      rationale: rationale.trim(),
    }
    if (verdict === 'modified' && modifications.trim()) {
      payload.modifications = { description: modifications.trim() }
    }
    if (conditions.trim()) {
      payload.conditions = {
        items: conditions
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
      }
    }
    mutation.mutate(payload)
  }

  if (mutation.isSuccess) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 text-sm text-emerald-900">
        <p className="font-medium">Decision recorded.</p>
        <p className="mt-1 text-xs text-emerald-800">
          Artifact ID: <span className="font-mono">{mutation.data.artifact_id}</span>.
          Hashes captured; case transitioned to <strong>decided</strong>.
        </p>
      </div>
    )
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-4 rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
    >
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Record decision</h3>
        <p className="mt-1 text-xs text-gray-500">
          Decision is irreversible. Six cryptographic hashes (evidence,
          synthesis, governance, portfolio risk, IC1, A1) are computed and
          persisted alongside the artifact for audit replay.
        </p>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-gray-600">Verdict</legend>
        {VERDICT_OPTIONS.map((opt) => (
          <label
            key={opt.value}
            className={`flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2 ${
              verdict === opt.value
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-200 hover:bg-gray-50'
            }`}
          >
            <input
              type="radio"
              name="verdict"
              value={opt.value}
              checked={verdict === opt.value}
              onChange={() => setVerdict(opt.value)}
              className="mt-0.5"
            />
            <div>
              <div className="text-sm font-medium text-gray-900">{opt.label}</div>
              <div className="text-xs text-gray-500">{opt.helper}</div>
            </div>
          </label>
        ))}
      </fieldset>

      <label className="block">
        <span className="text-xs font-medium text-gray-600">
          Rationale <span className="text-red-600">*</span>
        </span>
        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          rows={4}
          required
          className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="Why this decision? Will be hashed alongside the stage rows."
        />
      </label>

      {verdict === 'modified' && (
        <label className="block">
          <span className="text-xs font-medium text-gray-600">
            Modifications
          </span>
          <textarea
            value={modifications}
            onChange={(e) => setModifications(e.target.value)}
            rows={2}
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="What did you change vs the proposal? (e.g. 'reduced size by 30%')"
          />
        </label>
      )}

      <label className="block">
        <span className="text-xs font-medium text-gray-600">
          Conditions (one per line)
        </span>
        <textarea
          value={conditions}
          onChange={(e) => setConditions(e.target.value)}
          rows={2}
          className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="e.g.&#10;Review in 30 days&#10;Cap position at 8%"
        />
      </label>

      {mutation.error && (
        <p className="text-sm text-red-600">
          {mutation.error instanceof Error ? mutation.error.message : 'unknown error'}
        </p>
      )}

      <button
        type="submit"
        disabled={mutation.isPending || rationale.trim().length === 0}
        className="inline-flex items-center rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
        style={{ backgroundColor: 'var(--color-primary)' }}
      >
        {mutation.isPending ? 'Recording…' : 'Record Decision'}
      </button>
    </form>
  )
}
