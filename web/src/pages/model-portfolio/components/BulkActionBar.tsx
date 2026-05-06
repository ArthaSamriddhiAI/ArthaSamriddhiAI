import { Loader2, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { useState } from 'react'

import {
  ALL_HORIZONS,
  ALL_RISK_PROFILES,
  cellId,
  useBulkAddTag,
  useBulkRemoveTag,
  useBulkReplaceTags,
  useResetTagsToDefault,
} from '../../../api/modelPortfolio'
import { cn } from '../../../lib/cn'
import { CellGridSelector } from './CellGridSelector'
import { TagChip } from './TagChip'

// Cluster 4 chunk 4.2 bulk action bar. Visible when ≥1 instruments are
// selected; offers add-tag, remove-tag, replace-tag-set, and
// reset-to-default operations atomically across the selection.

type Mode = null | 'add' | 'remove' | 'replace' | 'reset'

export function BulkActionBar({
  selectedIds,
  onClear,
}: {
  selectedIds: string[]
  onClear: () => void
}) {
  const [mode, setMode] = useState<Mode>(null)
  if (selectedIds.length === 0) return null

  return (
    <div className="sticky top-0 z-30 mb-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 shadow-sm">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-sm font-medium text-amber-900">
          {selectedIds.length} instrument{selectedIds.length === 1 ? '' : 's'}{' '}
          selected
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setMode('add')}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <Plus size={12} /> Add Tag
          </button>
          <button
            type="button"
            onClick={() => setMode('remove')}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <Trash2 size={12} /> Remove Tag
          </button>
          <button
            type="button"
            onClick={() => setMode('replace')}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Replace Tags
          </button>
          <button
            type="button"
            onClick={() => setMode('reset')}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <RotateCcw size={12} /> Reset to Default
          </button>
          <button
            type="button"
            onClick={onClear}
            className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
          >
            <X size={12} /> Clear
          </button>
        </div>
      </div>

      {mode && (
        <BulkOperationModal
          mode={mode}
          selectedIds={selectedIds}
          onDone={() => {
            setMode(null)
            onClear()
          }}
          onCancel={() => setMode(null)}
        />
      )}
    </div>
  )
}

function BulkOperationModal({
  mode,
  selectedIds,
  onDone,
  onCancel,
}: {
  mode: Exclude<Mode, null>
  selectedIds: string[]
  onDone: () => void
  onCancel: () => void
}) {
  const [chosenTag, setChosenTag] = useState<string | null>(null)
  const [chosenSet, setChosenSet] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  const addMutation = useBulkAddTag()
  const removeMutation = useBulkRemoveTag()
  const replaceMutation = useBulkReplaceTags()
  const resetMutation = useResetTagsToDefault()

  const isPending =
    addMutation.isPending ||
    removeMutation.isPending ||
    replaceMutation.isPending ||
    resetMutation.isPending

  const allCells = ALL_RISK_PROFILES.flatMap((r) =>
    ALL_HORIZONS.map((h) => cellId(r, h)),
  )

  const onConfirm = () => {
    setError(null)
    const handleSuccess = () => onDone()
    const handleError = (err: Error) => setError(err.message)

    if (mode === 'add') {
      if (!chosenTag) return setError('Pick a tag')
      addMutation.mutate(
        { tag: chosenTag, instrumentIds: selectedIds },
        { onSuccess: handleSuccess, onError: handleError },
      )
    } else if (mode === 'remove') {
      if (!chosenTag) return setError('Pick a tag')
      removeMutation.mutate(
        { tag: chosenTag, instrumentIds: selectedIds },
        { onSuccess: handleSuccess, onError: handleError },
      )
    } else if (mode === 'replace') {
      replaceMutation.mutate(
        { tags: Array.from(chosenSet), instrumentIds: selectedIds },
        { onSuccess: handleSuccess, onError: handleError },
      )
    } else {
      resetMutation.mutate(
        { instrumentIds: selectedIds },
        { onSuccess: handleSuccess, onError: handleError },
      )
    }
  }

  const titles: Record<Exclude<Mode, null>, string> = {
    add: 'Add Tag to Selected',
    remove: 'Remove Tag from Selected',
    replace: 'Replace Tags on Selected',
    reset: 'Reset Tags to Default',
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-16"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-2xl rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {titles[mode]}
            </h2>
            <p className="text-sm text-gray-600">
              This action will affect {selectedIds.length} selected instrument
              {selectedIds.length === 1 ? '' : 's'}.
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-gray-400 hover:text-gray-700"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </header>

        <div className="px-6 py-5 space-y-4">
          {(mode === 'add' || mode === 'remove') && (
            <div>
              <label className="text-sm font-medium text-gray-700">
                Tag to {mode === 'add' ? 'add' : 'remove'}
              </label>
              <p className="text-xs text-gray-500 mb-2">
                {mode === 'add'
                  ? 'Pick the cell to mark all selected instruments as approved for.'
                  : 'Pick the cell to remove from all selected instruments.'}
              </p>
              <div className="flex flex-wrap gap-2">
                {allCells.map((cell) => (
                  <TagChip
                    key={cell}
                    cellId={cell}
                    selected={chosenTag === cell}
                    onClick={() => setChosenTag(cell)}
                  />
                ))}
              </div>
            </div>
          )}

          {mode === 'replace' && (
            <div>
              <label className="text-sm font-medium text-gray-700">
                New tag set
              </label>
              <p className="text-xs text-gray-500 mb-3">
                The selected instruments will be reset to exactly this tag set
                (overwriting any current tags).
              </p>
              <CellGridSelector selected={chosenSet} onChange={setChosenSet} />
            </div>
          )}

          {mode === 'reset' && (
            <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Selected instruments will be reset to the SEBI / vehicle-type
              default tags from the chunk 4.1 rule table. Any CIO
              customisations on the selected scope will be lost.
            </div>
          )}

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 px-6 py-3 border-t border-gray-200 bg-gray-50 rounded-b-lg">
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
            disabled={isPending}
            className={cn(
              'inline-flex items-center gap-1 rounded-md px-4 py-1.5 text-sm font-medium text-white shadow-sm',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {isPending && <Loader2 size={14} className="animate-spin" />}
            Confirm
          </button>
        </footer>
      </div>
    </div>
  )
}
