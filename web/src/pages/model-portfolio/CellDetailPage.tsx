import { Link, useParams } from '@tanstack/react-router'
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Loader2,
  Plus,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  type CellDetailResponse,
  type Horizon,
  type PositionRole,
  type PreferredPortfolioEntry,
  type RiskProfile,
  cellId,
  useCellDetail,
  useDeletePreferredEntry,
  useReorderCell,
  useResetCellToDefault,
  useUpdatePreferredEntry,
} from '../../api/modelPortfolio'
import { cn } from '../../lib/cn'
import { TagChip } from './components/TagChip'
import { AddEntryPanel } from './components/AddEntryPanel'

// Cluster 4 chunk 4.3 cell detail. Three role sections (core /
// satellite / optional) with entries listed in rank order. Within a
// section: move-up / move-down buttons + role-change dropdown + delete.
// Plus an "Add Entry" button that opens the tagged-but-not-preferred
// candidate picker. Read-only mode hides all edit affordances.

const RISK_LABELS: Record<RiskProfile, string> = {
  aggressive: 'Aggressive',
  moderate: 'Moderate',
  conservative: 'Conservative',
}

const HORIZON_LABELS: Record<Horizon, string> = {
  long_term: 'Long Term',
  medium_term: 'Medium Term',
  short_term: 'Short Term',
}

const RISK_TINT: Record<RiskProfile, string> = {
  aggressive: 'border-l-4 border-orange-400',
  moderate: 'border-l-4 border-green-400',
  conservative: 'border-l-4 border-blue-400',
}

interface Props {
  readOnly?: boolean
  matrixPath: string
}

export function CellDetailPage({ readOnly = false, matrixPath }: Props) {
  const params = useParams({ strict: false }) as {
    riskProfile?: string
    horizon?: string
  }
  const riskProfile = params.riskProfile as RiskProfile | undefined
  const horizon = params.horizon as Horizon | undefined

  const [showAddPanel, setShowAddPanel] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)

  const { data, isLoading, error } = useCellDetail(riskProfile, horizon)
  const resetMutation = useResetCellToDefault()

  if (!riskProfile || !horizon) {
    return (
      <div className="p-8 max-w-3xl">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Invalid cell URL.
        </div>
      </div>
    )
  }

  const cellLabel = `${RISK_LABELS[riskProfile]} / ${HORIZON_LABELS[horizon]}`
  const onResetCell = () => {
    setConfirmReset(false)
    resetMutation.mutate({ riskProfile, horizon })
  }

  return (
    <div className="p-8 max-w-5xl">
      <Link
        to={matrixPath as never}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to matrix
      </Link>

      <div className="flex items-start justify-between mb-4 flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">{cellLabel}</h1>
          <p className="text-sm text-gray-600 mt-1">
            Cell ID: <code>{cellId(riskProfile, horizon)}</code>
          </p>
        </div>
        {!readOnly && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowAddPanel(true)}
              className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium text-white shadow-sm"
              style={{ backgroundColor: 'var(--color-primary)' }}
            >
              <Plus size={14} /> Add Entry
            </button>
            <button
              type="button"
              onClick={() => setConfirmReset(true)}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <RotateCcw size={14} /> Reset Cell
            </button>
          </div>
        )}
      </div>

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
        <CellSections
          detail={data}
          riskProfile={riskProfile}
          horizon={horizon}
          readOnly={readOnly}
        />
      )}

      {showAddPanel && (
        <AddEntryPanel
          riskProfile={riskProfile}
          horizon={horizon}
          onClose={() => setShowAddPanel(false)}
        />
      )}

      {confirmReset && (
        <ConfirmModal
          title="Reset cell to default?"
          message={`This deletes all current entries in ${cellLabel} and reloads the cell from the default fixture. CIO customisations to this cell will be lost.`}
          onCancel={() => setConfirmReset(false)}
          onConfirm={onResetCell}
          pending={resetMutation.isPending}
        />
      )}
    </div>
  )
}

function CellSections({
  detail,
  riskProfile,
  horizon,
  readOnly,
}: {
  detail: CellDetailResponse
  riskProfile: RiskProfile
  horizon: Horizon
  readOnly: boolean
}) {
  return (
    <div className="space-y-6">
      <RoleSection
        title="Core"
        description="Foundational holdings — always included unless explicitly excluded by mandate."
        entries={detail.core}
        riskProfile={riskProfile}
        horizon={horizon}
        readOnly={readOnly}
        emphasis="strong"
      />
      <RoleSection
        title="Satellite"
        description="Complementary tilts — added when there's room beyond the cores."
        entries={detail.satellite}
        riskProfile={riskProfile}
        horizon={horizon}
        readOnly={readOnly}
        emphasis="medium"
      />
      <RoleSection
        title="Optional"
        description="Conditional add-ons — activated by specific investor needs (tax saving, gold, etc.)."
        entries={detail.optional}
        riskProfile={riskProfile}
        horizon={horizon}
        readOnly={readOnly}
        emphasis="muted"
      />
    </div>
  )
}

function RoleSection({
  title,
  description,
  entries,
  riskProfile,
  horizon,
  readOnly,
  emphasis,
}: {
  title: string
  description: string
  entries: PreferredPortfolioEntry[]
  riskProfile: RiskProfile
  horizon: Horizon
  readOnly: boolean
  emphasis: 'strong' | 'medium' | 'muted'
}) {
  return (
    <section
      className={cn(
        'rounded-lg shadow-sm',
        emphasis === 'strong' && 'bg-white border-2 border-gray-300',
        emphasis === 'medium' && 'bg-white border border-gray-200',
        emphasis === 'muted' && 'bg-gray-50 border border-gray-200',
      )}
    >
      <header className="px-4 py-3 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <h2
            className={cn(
              'font-semibold text-gray-900',
              emphasis === 'strong' ? 'text-base' : 'text-sm',
            )}
          >
            {title} <span className="text-gray-400">({entries.length})</span>
          </h2>
        </div>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </header>
      <div className="p-3 space-y-2">
        {entries.length === 0 ? (
          <div className="text-xs text-gray-400 italic px-2">
            No {title.toLowerCase()} entries yet.
          </div>
        ) : (
          entries.map((entry, idx) => (
            <EntryRow
              key={entry.entry_id}
              entry={entry}
              riskProfile={riskProfile}
              horizon={horizon}
              isFirst={idx === 0}
              isLast={idx === entries.length - 1}
              readOnly={readOnly}
              emphasis={emphasis}
            />
          ))
        )}
      </div>
    </section>
  )
}

function EntryRow({
  entry,
  riskProfile,
  horizon,
  isFirst,
  isLast,
  readOnly,
  emphasis,
}: {
  entry: PreferredPortfolioEntry
  riskProfile: RiskProfile
  horizon: Horizon
  isFirst: boolean
  isLast: boolean
  readOnly: boolean
  emphasis: 'strong' | 'medium' | 'muted'
}) {
  const updateMutation = useUpdatePreferredEntry()
  const deleteMutation = useDeletePreferredEntry()
  const reorderMutation = useReorderCell()

  const [notesEditing, setNotesEditing] = useState(false)
  const [notesDraft, setNotesDraft] = useState(entry.notes ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    setNotesDraft(entry.notes ?? '')
  }, [entry.entry_id, entry.notes])

  const onMove = (delta: -1 | 1) => {
    const newRank = Math.max(0, entry.rank_within_role + delta)
    reorderMutation.mutate({
      riskProfile,
      horizon,
      items: [
        {
          entry_id: entry.entry_id,
          position_role: entry.position_role,
          rank_within_role: newRank,
        },
      ],
    })
  }

  const onChangeRole = (newRole: PositionRole) => {
    if (newRole === entry.position_role) return
    updateMutation.mutate({
      entryId: entry.entry_id,
      positionRole: newRole,
    })
  }

  const onSaveNotes = () => {
    updateMutation.mutate(
      {
        entryId: entry.entry_id,
        notes: notesDraft.trim() || null,
      },
      { onSuccess: () => setNotesEditing(false) },
    )
  }

  return (
    <div
      className={cn(
        'rounded-md p-3 shadow-sm',
        RISK_TINT[riskProfile],
        emphasis === 'strong' ? 'bg-white' : 'bg-white/70',
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                'font-medium text-gray-900',
                emphasis === 'strong' ? 'text-base' : 'text-sm',
              )}
            >
              {entry.instrument_name}
            </span>
            <TagChip cellId={cellId(riskProfile, horizon)} size="sm" />
            {!entry.has_matching_tag && (
              <span
                className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-300"
                title="The instrument's tag set doesn't include this cell."
              >
                <AlertTriangle size={10} /> tag mismatch
              </span>
            )}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {entry.instrument_asset_class} · {entry.instrument_vehicle_type}
            {entry.instrument_amc_name && ` · ${entry.instrument_amc_name}`}
            {entry.instrument_sebi_category &&
              ` · ${entry.instrument_sebi_category}`}
          </div>
          <div className="text-xs text-gray-400 mt-0.5">
            Rank {entry.rank_within_role}
            {entry.last_modified_at && (
              <>
                {' '}
                · last modified{' '}
                {new Date(entry.last_modified_at).toLocaleDateString()}
                {' '}
                by {entry.last_modified_by}
              </>
            )}
          </div>
        </div>
        {!readOnly && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onMove(-1)}
              disabled={isFirst || reorderMutation.isPending}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-30"
              aria-label="Move up"
              title="Move up"
            >
              <ArrowUp size={14} />
            </button>
            <button
              type="button"
              onClick={() => onMove(1)}
              disabled={isLast || reorderMutation.isPending}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-30"
              aria-label="Move down"
              title="Move down"
            >
              <ArrowDown size={14} />
            </button>
            <select
              value={entry.position_role}
              onChange={(e) => onChangeRole(e.target.value as PositionRole)}
              disabled={updateMutation.isPending}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs"
              aria-label="Role"
            >
              <option value="core">core</option>
              <option value="satellite">satellite</option>
              <option value="optional">optional</option>
            </select>
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              disabled={deleteMutation.isPending}
              className="rounded p-1 text-red-500 hover:bg-red-50"
              aria-label="Delete entry"
              title="Delete entry"
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>

      <div className="mt-2 text-sm">
        {notesEditing && !readOnly ? (
          <div className="space-y-1">
            <textarea
              value={notesDraft}
              onChange={(e) => setNotesDraft(e.target.value)}
              maxLength={500}
              rows={2}
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1"
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onSaveNotes}
                disabled={updateMutation.isPending}
                className="rounded bg-gray-900 px-2 py-1 text-xs text-white hover:bg-gray-700 disabled:opacity-50"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  setNotesEditing(false)
                  setNotesDraft(entry.notes ?? '')
                }}
                className="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <span className="text-[10px] text-gray-400">
                {notesDraft.length}/500
              </span>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => !readOnly && setNotesEditing(true)}
            disabled={readOnly}
            className={cn(
              'text-left text-gray-700 italic w-full',
              !readOnly && 'hover:bg-gray-50 rounded px-1 -mx-1 cursor-text',
            )}
          >
            {entry.notes || (
              <span className="text-gray-400">
                {readOnly ? 'No notes' : 'Click to add notes…'}
              </span>
            )}
          </button>
        )}
      </div>

      {confirmDelete && (
        <ConfirmModal
          title="Delete this entry?"
          message={`Remove ${entry.instrument_name} from ${riskProfile} / ${horizon}? This cannot be undone (the audit log retains the record).`}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => {
            deleteMutation.mutate({ entryId: entry.entry_id })
            setConfirmDelete(false)
          }}
          pending={deleteMutation.isPending}
        />
      )}
    </div>
  )
}

function ConfirmModal({
  title,
  message,
  onCancel,
  onConfirm,
  pending,
}: {
  title: string
  message: string
  onCancel: () => void
  onConfirm: () => void
  pending: boolean
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-32"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between px-5 py-3 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          <button
            type="button"
            onClick={onCancel}
            className="text-gray-400 hover:text-gray-700"
          >
            <X size={18} />
          </button>
        </header>
        <div className="px-5 py-4 text-sm text-gray-700">{message}</div>
        <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-200 bg-gray-50 rounded-b-lg">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className={cn(
              'inline-flex items-center gap-1 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
          >
            {pending && <Loader2 size={14} className="animate-spin" />} Confirm
          </button>
        </footer>
      </div>
    </div>
  )
}
