import { Link } from '@tanstack/react-router'
import { ArrowLeft, ChevronLeft, ChevronRight, Edit2, Loader2, Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import {
  ALL_HORIZONS,
  ALL_RISK_PROFILES,
  cellId,
  type InstrumentWithTags,
  useModelPortfolioHealth,
  useModelPortfolioInstruments,
} from '../../api/modelPortfolio'
import { cn } from '../../lib/cn'
import { BulkActionBar } from './components/BulkActionBar'
import { TagChip } from './components/TagChip'
import { TagEditorModal } from './components/TagEditorModal'

// Cluster 4 chunk 4.2 tag editing surface. Renders the entire instrument
// universe with current tags as chips, supports filtering by asset
// class / vehicle / tag inclusion + exclusion / search / untagged-only,
// per-row "Edit Tags" button (read-only modal for advisors), and a
// bulk action bar when ≥1 instruments are selected.
//
// Same component is mounted at /app/cio/model-portfolio/instruments
// (read-write) and /app/advisor/model-portfolio/instruments (read-only).

const PAGE_SIZE = 50

const ASSET_CLASSES = ['equity', 'debt', 'cash', 'alternatives'] as const
const VEHICLE_TYPES = [
  'mutual_fund',
  'etf',
  'stock',
  'pms',
  'aif',
  'unlisted_equity',
] as const

interface Props {
  readOnly?: boolean
  /** Path to navigate back to from the page header. */
  backTo?: string
}

export function ModelPortfolioInstrumentsPage({
  readOnly = false,
  backTo = '/',
}: Props) {
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [assetClass, setAssetClass] = useState<string>('')
  const [vehicleType, setVehicleType] = useState<string>('')
  const [tagInclude, setTagInclude] = useState<string[]>([])
  const [tagExclude, setTagExclude] = useState<string[]>([])
  const [untaggedOnly, setUntaggedOnly] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [editingInstrument, setEditingInstrument] =
    useState<InstrumentWithTags | null>(null)

  const filters = useMemo(
    () => ({
      asset_class: assetClass || undefined,
      vehicle_type: vehicleType || undefined,
      tag_include: tagInclude.length ? tagInclude : undefined,
      tag_exclude: tagExclude.length ? tagExclude : undefined,
      untagged_only: untaggedOnly || undefined,
      search: search.trim() || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [assetClass, vehicleType, tagInclude, tagExclude, untaggedOnly, search, page],
  )

  const { data, isLoading, error } = useModelPortfolioInstruments(filters)
  const health = useModelPortfolioHealth()

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const toggleRow = (id: string, selected: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (selected) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const toggleAllVisible = (selected: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      for (const inst of data?.instruments ?? []) {
        if (selected) next.add(inst.instrument_id)
        else next.delete(inst.instrument_id)
      }
      return next
    })
  }

  const onClearFilters = () => {
    setSearch('')
    setAssetClass('')
    setVehicleType('')
    setTagInclude([])
    setTagExclude([])
    setUntaggedOnly(false)
    setPage(0)
  }

  const allCells = ALL_RISK_PROFILES.flatMap((r) =>
    ALL_HORIZONS.map((h) => cellId(r, h)),
  )

  return (
    <div className="p-8 max-w-7xl">
      <Link
        to={backTo}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back
      </Link>

      <div className="flex items-start justify-between mb-2">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">
            Tag Editing — Model Portfolio Universe
          </h1>
          <p className="text-sm text-gray-600 mt-1">
            {readOnly
              ? "View the firm's universe-level decisions about which instruments are appropriate for which client profiles."
              : 'Govern the boundary layer: which (risk_profile, horizon) cells each instrument is appropriate for. Bulk operations across selected rows are atomic.'}
          </p>
        </div>
        {health.data && (
          <div className="text-right text-xs text-gray-500 bg-white border border-gray-200 rounded-md px-3 py-2 shadow-sm">
            <div>
              <span className="font-semibold text-gray-700">
                {health.data.tagged_instruments_count}
              </span>{' '}
              of {health.data.total_instruments} tagged
            </div>
            {health.data.untagged_instruments_count > 0 && (
              <button
                type="button"
                onClick={() => {
                  setUntaggedOnly(true)
                  setPage(0)
                }}
                className="mt-1 text-amber-700 hover:underline"
              >
                {health.data.untagged_instruments_count} untagged →
              </button>
            )}
          </div>
        )}
      </div>

      {!readOnly && (
        <BulkActionBar
          selectedIds={Array.from(selectedIds)}
          onClear={() => setSelectedIds(new Set())}
        />
      )}

      <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm mb-4 space-y-3">
        <div className="flex flex-wrap gap-2 items-center">
          <div className="flex items-center gap-2 flex-1 min-w-[240px]">
            <Search size={14} className="text-gray-400" />
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(0)
              }}
              placeholder="Search name / ISIN / AMFI / ticker"
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1"
            />
          </div>
          <select
            value={assetClass}
            onChange={(e) => {
              setAssetClass(e.target.value)
              setPage(0)
            }}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="">All asset classes</option>
            {ASSET_CLASSES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            value={vehicleType}
            onChange={(e) => {
              setVehicleType(e.target.value)
              setPage(0)
            }}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="">All vehicles</option>
            {VEHICLE_TYPES.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
          <label className="inline-flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={untaggedOnly}
              onChange={(e) => {
                setUntaggedOnly(e.target.checked)
                setPage(0)
              }}
            />
            Untagged only
          </label>
          <button
            type="button"
            onClick={onClearFilters}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Clear
          </button>
        </div>

        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs font-medium text-gray-600 uppercase tracking-wider">
            Include cells:
          </span>
          {allCells.map((cell) => (
            <TagChip
              key={`inc-${cell}`}
              cellId={cell}
              size="sm"
              selected={tagInclude.includes(cell)}
              onClick={() => {
                setTagInclude((prev) =>
                  prev.includes(cell)
                    ? prev.filter((c) => c !== cell)
                    : [...prev, cell],
                )
                setPage(0)
              }}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs font-medium text-gray-600 uppercase tracking-wider">
            Exclude cells:
          </span>
          {allCells.map((cell) => (
            <TagChip
              key={`exc-${cell}`}
              cellId={cell}
              size="sm"
              selected={tagExclude.includes(cell)}
              onClick={() => {
                setTagExclude((prev) =>
                  prev.includes(cell)
                    ? prev.filter((c) => c !== cell)
                    : [...prev, cell],
                )
                setPage(0)
              }}
              className="opacity-70"
            />
          ))}
        </div>
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
        <>
          <div className="text-xs text-gray-500 mb-2">
            {total} matching instrument{total === 1 ? '' : 's'} · page {page + 1}{' '}
            of {totalPages}
          </div>
          {data.instruments.length === 0 ? (
            <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
              No instruments match these filters.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                  <tr>
                    {!readOnly && (
                      <th className="px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label="Select all visible"
                          checked={
                            data.instruments.length > 0 &&
                            data.instruments.every((i) =>
                              selectedIds.has(i.instrument_id),
                            )
                          }
                          onChange={(e) => toggleAllVisible(e.target.checked)}
                        />
                      </th>
                    )}
                    <th className="px-3 py-2 text-left">Name</th>
                    <th className="px-3 py-2 text-left">Class</th>
                    <th className="px-3 py-2 text-left">Vehicle</th>
                    <th className="px-3 py-2 text-left">Tags</th>
                    <th className="px-3 py-2 text-left">Last Modified</th>
                    {!readOnly && <th className="px-3 py-2" />}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.instruments.map((i) => (
                    <tr key={i.instrument_id}>
                      {!readOnly && (
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            aria-label={`Select ${i.name}`}
                            checked={selectedIds.has(i.instrument_id)}
                            onChange={(e) =>
                              toggleRow(i.instrument_id, e.target.checked)
                            }
                          />
                        </td>
                      )}
                      <td className="px-3 py-2">
                        <div className="text-gray-900">{i.name}</div>
                        <div className="text-[10px] text-gray-500 font-mono">
                          {i.isin || i.amfi_scheme_code || i.exchange_ticker || '—'}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-700">
                        {i.asset_class}
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-700">
                        {i.vehicle_type}
                      </td>
                      <td className="px-3 py-2">
                        {i.model_portfolio_tags.length === 0 ? (
                          <span className="text-xs text-amber-700 font-medium">
                            untagged
                          </span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {i.model_portfolio_tags.map((t) => (
                              <TagChip key={t} cellId={t} size="sm" />
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-500">
                        {i.model_portfolio_tags_modified_at ? (
                          <>
                            {new Date(
                              i.model_portfolio_tags_modified_at,
                            ).toLocaleDateString()}
                            <div className="text-[10px] text-gray-400">
                              by {i.model_portfolio_tags_modified_by}
                            </div>
                          </>
                        ) : (
                          <span className="italic text-gray-400">default</span>
                        )}
                      </td>
                      {!readOnly && (
                        <td className="px-3 py-2 text-right">
                          <button
                            type="button"
                            onClick={() => setEditingInstrument(i)}
                            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                          >
                            <Edit2 size={11} /> Edit
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm',
                  'disabled:cursor-not-allowed disabled:opacity-50',
                )}
              >
                <ChevronLeft size={14} /> Prev
              </button>
              <div className="text-sm text-gray-500">
                Page {page + 1} of {totalPages}
              </div>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm',
                  'disabled:cursor-not-allowed disabled:opacity-50',
                )}
              >
                Next <ChevronRight size={14} />
              </button>
            </div>
          )}
        </>
      )}

      {editingInstrument && (
        <TagEditorModal
          instrument={editingInstrument}
          open={true}
          onClose={() => setEditingInstrument(null)}
          readOnly={readOnly}
        />
      )}
    </div>
  )
}
