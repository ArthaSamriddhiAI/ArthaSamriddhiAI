import { Link } from '@tanstack/react-router'
import { ArrowRight, Loader2 } from 'lucide-react'

import {
  type Horizon,
  type RiskProfile,
  investorToCell,
  splitCell,
  useCellDetail,
} from '../../../api/modelPortfolio'
import { TagChip } from './TagChip'

// FR Entry 11.0 cluster-4 revision §2: investor profile cell linkage card.
// Renders on the investor profile, computes the cell from
// (risk_appetite, time_horizon), shows the badge, top-3 cores preview,
// click-through to the cell detail. Renders an "incomplete profile"
// fallback when either field is missing.

interface Props {
  riskAppetite: string | null | undefined
  timeHorizon: string | null | undefined
  /** Path prefix to the role's cell-detail surface. The advisor profile
   * mounts this card and links into ``/advisor/model-portfolio/preferred``;
   * the CIO surface (when reused in cluster 5+) into the CIO equivalent. */
  cellPathPrefix: string
}

export function InvestorCellLinkageCard({
  riskAppetite,
  timeHorizon,
  cellPathPrefix,
}: Props) {
  const cell = investorToCell({
    riskAppetite,
    timeHorizon,
  })

  if (!cell) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <div className="text-sm font-semibold text-gray-900 mb-2">
          Model Portfolio
        </div>
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <div className="font-medium mb-0.5">Cell unknown</div>
          <p className="text-xs">
            Investor profile is incomplete. Set risk appetite and time horizon
            to determine the model portfolio cell.
          </p>
        </div>
      </div>
    )
  }

  const split = splitCell(cell)
  if (!split) return null
  const [riskProfile, horizon] = split

  return (
    <CellLinkageContent
      cell={cell}
      riskProfile={riskProfile}
      horizon={horizon}
      cellPathPrefix={cellPathPrefix}
    />
  )
}

function CellLinkageContent({
  cell,
  riskProfile,
  horizon,
  cellPathPrefix,
}: {
  cell: string
  riskProfile: RiskProfile
  horizon: Horizon
  cellPathPrefix: string
}) {
  const detail = useCellDetail(riskProfile, horizon)

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-gray-900">
          Model Portfolio
        </div>
        <TagChip cellId={cell} size="md" />
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Preferred portfolio for {riskProfile.replace('_', ' ')} risk,{' '}
        {horizon.replace('_', ' ')} horizon.
      </p>

      {detail.isLoading && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Loader2 size={12} className="animate-spin" /> Loading…
        </div>
      )}

      {detail.data && (
        <div className="space-y-2 mb-3">
          {detail.data.core.length > 0 ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                Core ({detail.data.core.length})
              </div>
              <ul className="text-xs text-gray-700 space-y-0.5">
                {detail.data.core.slice(0, 3).map((e) => (
                  <li key={e.entry_id} className="truncate">
                    · {e.instrument_name}
                  </li>
                ))}
                {detail.data.core.length > 3 && (
                  <li className="text-gray-400 italic">
                    + {detail.data.core.length - 3} more
                  </li>
                )}
              </ul>
            </div>
          ) : (
            <div className="text-xs text-gray-500 italic">
              No preferred entries in this cell yet.
            </div>
          )}
        </div>
      )}

      <Link
        to={`${cellPathPrefix}/${riskProfile}/${horizon}` as never}
        className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-900"
      >
        View full preferred portfolio <ArrowRight size={12} />
      </Link>
    </div>
  )
}
