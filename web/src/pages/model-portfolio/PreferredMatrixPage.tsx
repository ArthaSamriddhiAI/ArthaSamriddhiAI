import { Link } from '@tanstack/react-router'
import { ArrowLeft, ArrowRight, Loader2 } from 'lucide-react'

import {
  ALL_HORIZONS,
  ALL_RISK_PROFILES,
  type CellSummary,
  type Horizon,
  type RiskProfile,
  cellId,
  useMatrixOverview,
} from '../../api/modelPortfolio'
import { cn } from '../../lib/cn'

// Cluster 4 chunk 4.3 matrix overview. The 3x3 grid of cells rendered as
// interactive cards: counts by role, last-modified, top-3 cores in
// hover preview, click-through to cell detail.
//
// The CIO and advisor surfaces share this component; advisor view links
// to the same cell detail (which itself renders read-only when the user
// lacks MODEL_PORTFOLIO_WRITE).

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
  aggressive: 'bg-orange-50 border-orange-300',
  moderate: 'bg-green-50 border-green-300',
  conservative: 'bg-blue-50 border-blue-300',
}

const HORIZON_BORDER: Record<Horizon, string> = {
  long_term: 'border-solid border-[1.5px]',
  medium_term: 'border-dashed border-[1.5px]',
  short_term: 'border-solid border-[1px] border-opacity-60',
}

interface Props {
  /** Where the page header's "back" link points to. */
  backTo?: string
  /** Path prefix used by cell-card click-through, e.g. '/cio/model-portfolio/preferred'
   * or '/advisor/model-portfolio/preferred'. */
  cellPathPrefix: string
}

export function PreferredMatrixPage({
  backTo = '/',
  cellPathPrefix,
}: Props) {
  const { data, isLoading, error } = useMatrixOverview()

  return (
    <div className="p-8 max-w-6xl">
      <Link
        to={backTo}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back
      </Link>

      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">
            Preferred Portfolio
          </h1>
          <p className="text-sm text-gray-600 mt-1 max-w-3xl">
            The firm's curated preferred portfolio across the 3x3 client-profile
            matrix. Each cell holds core / satellite / optional entries —
            click into a cell to view or edit its detail.
          </p>
        </div>
        {data && (
          <div className="text-right text-xs text-gray-500 bg-white border border-gray-200 rounded-md px-3 py-2 shadow-sm">
            <div>
              <span className="font-semibold text-gray-700">
                {data.total_entries}
              </span>{' '}
              entries across 9 cells
            </div>
            {data.last_modified_at && (
              <div className="mt-0.5">
                Last modified{' '}
                {new Date(data.last_modified_at).toLocaleDateString()}
              </div>
            )}
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
        <div className="grid grid-cols-[140px_repeat(3,1fr)] gap-3">
          <div />
          {ALL_HORIZONS.map((h) => (
            <div
              key={h}
              className="text-center text-xs font-semibold uppercase tracking-wider text-gray-500"
            >
              {HORIZON_LABELS[h]}
            </div>
          ))}
          {ALL_RISK_PROFILES.map((r) => (
            <CellRow
              key={r}
              riskProfile={r}
              cells={data.cells}
              cellPathPrefix={cellPathPrefix}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CellRow({
  riskProfile,
  cells,
  cellPathPrefix,
}: {
  riskProfile: RiskProfile
  cells: CellSummary[]
  cellPathPrefix: string
}) {
  return (
    <>
      <div className="text-right text-xs font-semibold uppercase tracking-wider text-gray-500 pr-2 self-center">
        {RISK_LABELS[riskProfile]}
      </div>
      {ALL_HORIZONS.map((h) => {
        const summary = cells.find(
          (c) => c.risk_profile === riskProfile && c.horizon === h,
        )
        if (!summary) return <div key={h} />
        return (
          <CellCard
            key={h}
            summary={summary}
            cellPathPrefix={cellPathPrefix}
          />
        )
      })}
    </>
  )
}

function CellCard({
  summary,
  cellPathPrefix,
}: {
  summary: CellSummary
  cellPathPrefix: string
}) {
  const total =
    summary.counts.core + summary.counts.satellite + summary.counts.optional
  const fullness =
    total === 0
      ? 'empty'
      : total < 4
      ? 'thin'
      : 'healthy'
  const fullnessColor =
    fullness === 'healthy'
      ? 'bg-green-500'
      : fullness === 'thin'
      ? 'bg-amber-500'
      : 'bg-red-500'

  return (
    <Link
      to={`${cellPathPrefix}/${summary.risk_profile}/${summary.horizon}` as never}
      className={cn(
        'group block rounded-lg p-4 shadow-sm hover:shadow-md transition relative',
        RISK_TINT[summary.risk_profile],
        HORIZON_BORDER[summary.horizon],
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold text-gray-900">
          {total} entries
        </span>
        <span
          className={cn('h-2 w-2 rounded-full', fullnessColor)}
          title={fullness}
        />
      </div>
      <div className="text-xs text-gray-700 space-y-0.5">
        <div>
          <span className="font-medium">Core:</span> {summary.counts.core}
        </div>
        <div>
          <span className="font-medium">Satellite:</span>{' '}
          {summary.counts.satellite}
        </div>
        <div>
          <span className="font-medium">Optional:</span>{' '}
          {summary.counts.optional}
        </div>
      </div>
      {summary.top_core_names.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-200 border-opacity-50">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">
            Top cores
          </div>
          <ul className="text-[10px] text-gray-600 space-y-0.5">
            {summary.top_core_names.map((name) => (
              <li key={name} className="truncate">
                · {name}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-2 flex items-center justify-end">
        <ArrowRight
          size={14}
          className="text-gray-400 opacity-0 group-hover:opacity-100 transition"
        />
      </div>
      {summary.last_modified_at && (
        <div className="mt-1 text-[10px] text-gray-500">
          {new Date(summary.last_modified_at).toLocaleDateString()}
        </div>
      )}
    </Link>
  )
}

export { cellId }
