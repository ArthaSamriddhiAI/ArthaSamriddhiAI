import { Loader2, Plus, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import {
  type Horizon,
  type PositionRole,
  type RiskProfile,
  cellId,
  useCellDetail,
  useCreatePreferredEntry,
  useModelPortfolioInstruments,
} from '../../../api/modelPortfolio'
import { cn } from '../../../lib/cn'

// Cluster 4 chunk 4.3 add-entry panel. Right-side sheet showing tagged
// instruments NOT yet in the cell. Click to select, choose role, save.
//
// Implementation note: the chunk plan §scope_in calls for a "tagged but
// not preferred" surface. We achieve this by listing tagged instruments
// with the target cell's tag included, then client-side filtering out
// those already preferred in the cell.

interface Props {
  riskProfile: RiskProfile
  horizon: Horizon
  onClose: () => void
}

export function AddEntryPanel({ riskProfile, horizon, onClose }: Props) {
  const [search, setSearch] = useState('')
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<
    string | null
  >(null)
  const [role, setRole] = useState<PositionRole>('satellite')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  const targetCellId = cellId(riskProfile, horizon)

  // Tagged-for-this-cell candidates (chunk 4.2 endpoint).
  const candidates = useModelPortfolioInstruments({
    tag_include: [targetCellId],
    search: search.trim() || undefined,
    limit: 200,
  })

  // Already-preferred instruments — exclude these from the candidate list.
  const cell = useCellDetail(riskProfile, horizon)
  const alreadyPreferredIds = useMemo(() => {
    if (!cell.data) return new Set<string>()
    const ids = new Set<string>()
    for (const e of [
      ...cell.data.core,
      ...cell.data.satellite,
      ...cell.data.optional,
    ]) {
      ids.add(e.instrument_id)
    }
    return ids
  }, [cell.data])

  const filtered = useMemo(() => {
    if (!candidates.data) return []
    return candidates.data.instruments.filter(
      (i) => !alreadyPreferredIds.has(i.instrument_id),
    )
  }, [candidates.data, alreadyPreferredIds])

  const createMutation = useCreatePreferredEntry()

  const onSave = () => {
    if (!selectedInstrumentId) {
      setError('Pick an instrument from the list')
      return
    }
    setError(null)
    createMutation.mutate(
      {
        riskProfile,
        horizon,
        instrumentId: selectedInstrumentId,
        positionRole: role,
        rankWithinRole: 0,
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: () => onClose(),
        onError: (err) => setError(err.message),
      },
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-white shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between px-5 py-3 border-b border-gray-200">
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              Add Entry to {riskProfile} / {horizon.replace('_', ' ')}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Pick from instruments tagged for this cell that aren't already
              in its preferred portfolio.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700"
          >
            <X size={18} />
          </button>
        </header>

        <div className="px-5 py-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <Search size={14} className="text-gray-400" />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name / ISIN / AMFI"
              className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {candidates.isLoading ? (
            <div className="flex items-center gap-2 p-5 text-sm text-gray-500">
              <Loader2 size={16} className="animate-spin" /> Loading
              candidates…
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-5 text-sm text-gray-500">
              No tagged instruments are available for this cell. Tag more
              instruments via the tag editor first.
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {filtered.slice(0, 100).map((i) => (
                <li
                  key={i.instrument_id}
                  className={cn(
                    'cursor-pointer px-5 py-2.5 hover:bg-gray-50 transition',
                    selectedInstrumentId === i.instrument_id && 'bg-blue-50',
                  )}
                  onClick={() => setSelectedInstrumentId(i.instrument_id)}
                >
                  <div className="flex items-start gap-2">
                    <input
                      type="radio"
                      checked={selectedInstrumentId === i.instrument_id}
                      readOnly
                      className="mt-1"
                      aria-label={`Select ${i.name}`}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-gray-900">{i.name}</div>
                      <div className="text-xs text-gray-500">
                        {i.asset_class} · {i.vehicle_type}
                        {i.amc_name && ` · ${i.amc_name}`}
                      </div>
                    </div>
                  </div>
                </li>
              ))}
              {filtered.length > 100 && (
                <li className="px-5 py-3 text-xs text-gray-500 italic">
                  Showing first 100 of {filtered.length} — refine the search to
                  narrow down.
                </li>
              )}
            </ul>
          )}
        </div>

        {selectedInstrumentId && (
          <div className="px-5 py-3 border-t border-gray-200 space-y-2 bg-gray-50">
            <div>
              <label className="text-xs font-medium text-gray-700">Role</label>
              <div className="flex items-center gap-3 mt-1 text-xs">
                {(['core', 'satellite', 'optional'] as PositionRole[]).map(
                  (r) => (
                    <label
                      key={r}
                      className="inline-flex items-center gap-1 cursor-pointer"
                    >
                      <input
                        type="radio"
                        name="role"
                        value={r}
                        checked={role === r}
                        onChange={() => setRole(r)}
                      />
                      {r}
                    </label>
                  ),
                )}
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700">
                Notes (optional)
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                maxLength={500}
                placeholder="Why this instrument in this cell?"
                className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-offset-1"
              />
            </div>
          </div>
        )}

        {error && (
          <div className="px-5 py-2 border-t border-red-200 bg-red-50 text-sm text-red-700">
            {error}
          </div>
        )}

        <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-200 bg-white">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!selectedInstrumentId || createMutation.isPending}
            className={cn(
              'inline-flex items-center gap-1 rounded-md px-4 py-1.5 text-sm font-medium text-white shadow-sm',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {createMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Plus size={14} />
            )}
            Add Entry
          </button>
        </footer>
      </div>
    </div>
  )
}
