import {
  ALL_HORIZONS,
  ALL_RISK_PROFILES,
  cellId,
  type Horizon,
  type RiskProfile,
} from '../../../api/modelPortfolio'
import { cn } from '../../../lib/cn'

// Cluster 4 chunk 4.2 cell-grid selector. The 3x3 matrix of cell
// identifiers as a checkbox grid; used inside the tag editor modal and
// the bulk-replace confirmation. Read-only mode disables the
// checkboxes so advisor surfaces can render the same grid.

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
  aggressive: 'bg-orange-50/50',
  moderate: 'bg-green-50/50',
  conservative: 'bg-blue-50/50',
}

const HORIZON_BORDER: Record<Horizon, string> = {
  long_term: 'border-solid border-[1.5px]',
  medium_term: 'border-dashed border-[1.5px]',
  short_term: 'border-solid border-[1px] border-opacity-60',
}

export function CellGridSelector({
  selected,
  onChange,
  disabled = false,
  highlightDefault,
}: {
  selected: Set<string>
  onChange: (next: Set<string>) => void
  disabled?: boolean
  highlightDefault?: Set<string>
}) {
  const toggle = (cell: string) => {
    if (disabled) return
    const next = new Set(selected)
    if (next.has(cell)) next.delete(cell)
    else next.add(cell)
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[140px_repeat(3,1fr)] gap-1">
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
          <>
            <div
              key={`label-${r}`}
              className="text-right text-xs font-semibold uppercase tracking-wider text-gray-500 pr-2 self-center"
            >
              {RISK_LABELS[r]}
            </div>
            {ALL_HORIZONS.map((h) => {
              const cell = cellId(r, h)
              const isSelected = selected.has(cell)
              const isDefault = highlightDefault?.has(cell)
              return (
                <button
                  key={cell}
                  type="button"
                  onClick={() => toggle(cell)}
                  disabled={disabled}
                  className={cn(
                    'flex flex-col items-center justify-center rounded p-2 min-h-[60px] transition',
                    RISK_TINT[r],
                    HORIZON_BORDER[h],
                    isSelected
                      ? 'ring-2 ring-current ring-offset-1 font-semibold'
                      : 'hover:brightness-95',
                    disabled && 'cursor-not-allowed opacity-60',
                  )}
                  title={cell.replace(/_/g, ' ')}
                  aria-pressed={isSelected}
                  aria-label={`${RISK_LABELS[r]} ${HORIZON_LABELS[h]}`}
                >
                  <span className="text-[10px] uppercase tracking-wider">
                    {RISK_LABELS[r]}
                  </span>
                  <span className="text-[10px]">{HORIZON_LABELS[h]}</span>
                  {isDefault && !isSelected && (
                    <span className="text-[9px] text-gray-400 mt-0.5">
                      default
                    </span>
                  )}
                  {isSelected && (
                    <span className="text-[10px] mt-0.5">✓</span>
                  )}
                </button>
              )
            })}
          </>
        ))}
      </div>
      <div className="text-xs text-gray-500 mt-2">
        Cool blue · conservative · cooling tone. Neutral green ·
        moderate · balanced. Warm orange · aggressive · forward tone.
        Solid border · long term. Dashed · medium term. Light · short term.
      </div>
    </div>
  )
}
