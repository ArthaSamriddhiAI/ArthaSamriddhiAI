import { Loader2, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  type InstrumentWithTags,
  useReplaceInstrumentTags,
} from '../../../api/modelPortfolio'
import { cn } from '../../../lib/cn'
import { CellGridSelector } from './CellGridSelector'

// Cluster 4 chunk 4.2 single-instrument tag editor. Opens on "Edit Tags"
// click; renders the 3x3 grid pre-checked with the instrument's current
// tags. Read-only mode hides the save action and disables the grid so
// advisors can use the same modal for inspection.

interface Props {
  instrument: InstrumentWithTags
  open: boolean
  onClose: () => void
  readOnly?: boolean
  /** When set, the grid renders 'default' hints on cells that aren't
   * currently selected but ARE in the instrument's default tag set. */
  defaultHints?: Set<string>
}

export function TagEditorModal({
  instrument,
  open,
  onClose,
  readOnly = false,
  defaultHints,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(instrument.model_portfolio_tags),
  )
  const [error, setError] = useState<string | null>(null)
  const replaceMutation = useReplaceInstrumentTags()

  // Reset selection when the modal reopens for a different instrument.
  useEffect(() => {
    if (open) {
      setSelected(new Set(instrument.model_portfolio_tags))
      setError(null)
    }
  }, [open, instrument.instrument_id, instrument.model_portfolio_tags])

  if (!open) return null

  const isDirty = !setEquals(selected, new Set(instrument.model_portfolio_tags))
  const onSave = () => {
    setError(null)
    replaceMutation.mutate(
      {
        instrumentId: instrument.instrument_id,
        tags: Array.from(selected),
      },
      {
        onSuccess: () => onClose(),
        onError: (err) => setError(err.message),
      },
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {readOnly ? 'View Tags' : 'Edit Tags'}
            </h2>
            <p className="text-sm text-gray-600 truncate">
              {instrument.name}
            </p>
            <p className="text-xs text-gray-500">
              {instrument.asset_class} · {instrument.vehicle_type}
              {instrument.sebi_category && ` · ${instrument.sebi_category}`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </header>

        <div className="px-6 py-5 space-y-4">
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">
              Approved cells
            </h3>
            <p className="text-xs text-gray-500 mb-3">
              Toggle cells to mark this instrument as appropriate for those
              client profiles. Tagged instruments become eligible for the
              firm's preferred portfolio in those cells.
            </p>
            <CellGridSelector
              selected={selected}
              onChange={setSelected}
              disabled={readOnly}
              highlightDefault={defaultHints}
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-2 px-6 py-3 border-t border-gray-200 bg-gray-50 rounded-b-lg">
          <div className="text-xs text-gray-500">
            {selected.size} of 9 cells selected
            {!readOnly && isDirty && (
              <span className="ml-2 text-amber-700 font-medium">·  unsaved</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
            >
              {readOnly ? 'Close' : 'Cancel'}
            </button>
            {!readOnly && (
              <button
                type="button"
                onClick={onSave}
                disabled={!isDirty || replaceMutation.isPending}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-4 py-1.5 text-sm font-medium text-white shadow-sm',
                  'disabled:cursor-not-allowed disabled:opacity-50',
                )}
                style={{ backgroundColor: 'var(--color-primary)' }}
              >
                {replaceMutation.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Save Tags
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  )
}

function setEquals(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false
  for (const v of a) if (!b.has(v)) return false
  return true
}
