import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { useInvestor } from '../../api/investors'
import {
  type MandateCreatePayload,
  type MandateVersion,
  useActiveMandate,
  useProposeAmendment,
  useSubmitAmendment,
  useUpdateDraft,
  useMandateVersions,
} from '../../api/mandates'
import { cn } from '../../lib/cn'

// Per chunk plan §2.3 §scope_in:
//   "Amendment editor UI at /app/advisor/investors/{id}/mandate/amend:
//     reuses the form layout from chunk 2.1 with current active values
//     pre-populated. Shows what's changed visually as the advisor edits."
//
// Cluster 2 ships a simpler edit UI than chunk 2.1's full create form to
// keep the diff focused: numerical constraints in a flat grid, prohibited
// list as a tag input. Each field shows a "Modified" badge when its value
// diverges from the active version.

export function AmendMandatePage() {
  const { investorId } = useParams({ strict: false }) as { investorId: string }
  const navigate = useNavigate()
  const investorQuery = useInvestor(investorId)
  const activeQuery = useActiveMandate(investorId)
  const versionsQuery = useMandateVersions(investorId)
  const proposeMutation = useProposeAmendment(investorId)

  // The amendment editor either resumes an existing draft or proposes a
  // fresh one. The "draft" version is whatever non-active version exists
  // (status=draft or pending_approval, but pending shouldn't be editable).
  const draft = useMemo(() => {
    return (
      versionsQuery.data?.find(
        (v) => v.status === 'draft' || v.status === 'pending_approval',
      ) ?? null
    )
  }, [versionsQuery.data])

  // On mount, if there's no draft, propose one.
  useEffect(() => {
    if (!versionsQuery.data) return
    if (draft !== null) return
    if (proposeMutation.isPending) return
    if (proposeMutation.isSuccess || proposeMutation.isError) return
    proposeMutation.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionsQuery.data, draft, proposeMutation.isPending])

  const active = activeQuery.data?.active_version ?? null

  if (
    investorQuery.isLoading
    || activeQuery.isLoading
    || versionsQuery.isLoading
  ) {
    return (
      <div className="p-8 max-w-3xl flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin" /> Loading…
      </div>
    )
  }

  if (!investorQuery.data || !active) {
    return (
      <div className="p-8 max-w-3xl">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          No active mandate to amend. Create one first.
        </div>
      </div>
    )
  }

  if (proposeMutation.isError) {
    return (
      <div className="p-8 max-w-3xl">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {proposeMutation.error.message}
        </div>
      </div>
    )
  }

  if (!draft) {
    // Still proposing the draft.
    return (
      <div className="p-8 max-w-3xl flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin" /> Preparing draft…
      </div>
    )
  }

  // Drafts that are pending_approval shouldn't be editable; show read-only.
  if (draft.status === 'pending_approval') {
    return (
      <div className="p-8 max-w-3xl">
        <Link
          to="/investors/$investorId"
          params={{ investorId }}
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
        >
          <ArrowLeft size={14} aria-hidden="true" />
          Back to investor
        </Link>
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          This amendment is pending CIO approval. You'll be notified when it's
          reviewed.
        </div>
      </div>
    )
  }

  return (
    <AmendEditor
      investorName={investorQuery.data.name}
      investorId={investorId}
      active={active}
      draft={draft}
      onCancel={() =>
        navigate({
          to: '/investors/$investorId',
          params: { investorId },
        })
      }
    />
  )
}


// ---------------------------------------------------------------------------
// Editor proper
// ---------------------------------------------------------------------------


interface EditorProps {
  investorId: string
  investorName: string
  active: MandateVersion
  draft: MandateVersion
  onCancel: () => void
}


function AmendEditor({
  investorId,
  investorName,
  active,
  draft,
  onCancel,
}: EditorProps) {
  const updateDraft = useUpdateDraft(draft.version_id)
  const submitMutation = useSubmitAmendment(draft.version_id)
  const navigate = useNavigate()

  const [values, setValues] = useState<MandateCreatePayload>({
    equity_min_pct: draft.equity_min_pct,
    equity_max_pct: draft.equity_max_pct,
    debt_min_pct: draft.debt_min_pct,
    debt_max_pct: draft.debt_max_pct,
    alternatives_min_pct: draft.alternatives_min_pct,
    alternatives_max_pct: draft.alternatives_max_pct,
    single_position_max_pct: draft.single_position_max_pct,
    liquidity_floor_pct: draft.liquidity_floor_pct,
    sector_max_pct: draft.sector_max_pct,
    prohibited_instruments: [...draft.prohibited_instruments],
  })

  const modified = useMemo(() => {
    const fields = new Set<string>()
    for (const key of Object.keys(values) as Array<keyof MandateCreatePayload>) {
      if (key === 'prohibited_instruments') continue
      if ((values[key] as number) !== (active[key] as number)) {
        fields.add(key)
      }
    }
    if (
      JSON.stringify([...values.prohibited_instruments].sort())
      !== JSON.stringify([...active.prohibited_instruments].sort())
    ) {
      fields.add('prohibited_instruments')
    }
    return fields
  }, [values, active])

  const handleSave = () => {
    updateDraft.mutate(values)
  }

  const handleSubmit = () => {
    updateDraft.mutate(values, {
      onSuccess: () => {
        submitMutation.mutate(undefined, {
          onSuccess: () =>
            navigate({
              to: '/investors/$investorId',
              params: { investorId },
            }),
        })
      },
    })
  }

  return (
    <div className="p-8 max-w-3xl">
      <Link
        to="/investors/$investorId"
        params={{ investorId }}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to investor
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-1">
        Amend {investorName}'s Mandate
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Editing version {draft.version_number} (draft). Changes activate after
        CIO approval. Modified fields are highlighted.
      </p>

      {draft.changes_requested_comments && (
        <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm">
          <div className="font-medium text-amber-900 mb-1">
            CIO requested changes:
          </div>
          <div className="text-amber-900">{draft.changes_requested_comments}</div>
        </div>
      )}

      {(updateDraft.error || submitMutation.error) && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {updateDraft.error?.message || submitMutation.error?.message}
        </div>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <BandPair
            label="Equity"
            minKey="equity_min_pct"
            maxKey="equity_max_pct"
            values={values}
            setValues={setValues}
            modified={
              modified.has('equity_min_pct') || modified.has('equity_max_pct')
            }
          />
          <BandPair
            label="Debt"
            minKey="debt_min_pct"
            maxKey="debt_max_pct"
            values={values}
            setValues={setValues}
            modified={
              modified.has('debt_min_pct') || modified.has('debt_max_pct')
            }
          />
          <BandPair
            label="Alternatives"
            minKey="alternatives_min_pct"
            maxKey="alternatives_max_pct"
            values={values}
            setValues={setValues}
            modified={
              modified.has('alternatives_min_pct')
              || modified.has('alternatives_max_pct')
            }
          />
        </div>
        <PercentRow
          label="Single-position max (%)"
          fieldKey="single_position_max_pct"
          values={values}
          setValues={setValues}
          modified={modified.has('single_position_max_pct')}
        />
        <PercentRow
          label="Liquidity floor (%)"
          fieldKey="liquidity_floor_pct"
          values={values}
          setValues={setValues}
          modified={modified.has('liquidity_floor_pct')}
        />
        <PercentRow
          label="Sector cap (%)"
          fieldKey="sector_max_pct"
          values={values}
          setValues={setValues}
          modified={modified.has('sector_max_pct')}
        />
      </section>

      <div className="mt-6 flex justify-end gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={updateDraft.isPending}
          className={cn(
            'rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700',
            'hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60',
          )}
        >
          {updateDraft.isPending ? 'Saving…' : 'Save Draft'}
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={updateDraft.isPending || submitMutation.isPending || modified.size === 0}
          className={cn(
            'rounded-md px-5 py-2 text-sm font-medium text-white shadow-sm',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          {submitMutation.isPending ? 'Submitting…' : 'Submit for Approval'}
        </button>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------


function PercentRow({
  label,
  fieldKey,
  values,
  setValues,
  modified,
}: {
  label: string
  fieldKey: keyof MandateCreatePayload
  values: MandateCreatePayload
  setValues: (next: MandateCreatePayload) => void
  modified: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="text-sm text-gray-700 flex items-center gap-2">
        {label}
        {modified && (
          <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-[10px] font-semibold text-yellow-900 ring-1 ring-yellow-300">
            Modified
          </span>
        )}
      </div>
      <input
        type="number"
        min={0}
        max={100}
        value={values[fieldKey] as number}
        onChange={(e) =>
          setValues({ ...values, [fieldKey]: Number(e.target.value) })
        }
        className={cn(
          'w-32 rounded-md border border-gray-300 px-3 py-2 text-sm',
          'focus:outline-none focus:ring-2 focus:ring-offset-1',
        )}
      />
    </div>
  )
}


function BandPair({
  label,
  minKey,
  maxKey,
  values,
  setValues,
  modified,
}: {
  label: string
  minKey: keyof MandateCreatePayload
  maxKey: keyof MandateCreatePayload
  values: MandateCreatePayload
  setValues: (next: MandateCreatePayload) => void
  modified: boolean
}) {
  return (
    <div className="col-span-1 sm:col-span-2">
      <div className="text-sm font-medium text-gray-700 mb-1 flex items-center gap-2">
        {label}
        {modified && (
          <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-[10px] font-semibold text-yellow-900 ring-1 ring-yellow-300">
            Modified
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          max={100}
          value={values[minKey] as number}
          onChange={(e) =>
            setValues({ ...values, [minKey]: Number(e.target.value) })
          }
          aria-label={`${label} min`}
          className="w-24 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1"
        />
        <span className="text-sm text-gray-500">to</span>
        <input
          type="number"
          min={0}
          max={100}
          value={values[maxKey] as number}
          onChange={(e) =>
            setValues({ ...values, [maxKey]: Number(e.target.value) })
          }
          aria-label={`${label} max`}
          className="w-24 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1"
        />
        <span className="text-sm text-gray-500">%</span>
      </div>
    </div>
  )
}
