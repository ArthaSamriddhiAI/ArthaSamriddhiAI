import { cn } from '../../../lib/cn'
import { type Horizon, type RiskProfile, splitCell } from '../../../api/modelPortfolio'

// Cluster 4 chunk 4.2 tag chip — color by risk profile (cool blue / neutral
// green / warm orange) and shape via border style (solid / dashed / light)
// by horizon. Per FR Entry 13.0 §4.4 conventions, used consistently
// across the chunk 4.2 tag editing UI, the chunk 4.3 preferred portfolio
// matrix, and the FR 11.0 cluster-4 revision investor profile cell badge.

const RISK_STYLES: Record<RiskProfile, string> = {
  conservative: 'bg-blue-50 text-blue-900 border-blue-300',
  moderate: 'bg-green-50 text-green-900 border-green-300',
  aggressive: 'bg-orange-50 text-orange-900 border-orange-300',
}

const HORIZON_STYLES: Record<Horizon, string> = {
  long_term: 'border-solid border-[1.5px]',
  medium_term: 'border-dashed border-[1.5px]',
  short_term: 'border-solid border-[1px] opacity-90',
}

const HORIZON_LABELS: Record<Horizon, string> = {
  long_term: 'LT',
  medium_term: 'MT',
  short_term: 'ST',
}

const RISK_LABELS: Record<RiskProfile, string> = {
  aggressive: 'Aggr',
  moderate: 'Mod',
  conservative: 'Cons',
}

export function TagChip({
  cellId,
  size = 'md',
  selected = false,
  onClick,
  className,
}: {
  cellId: string
  size?: 'sm' | 'md' | 'lg'
  selected?: boolean
  onClick?: () => void
  className?: string
}) {
  const split = splitCell(cellId)
  if (!split) {
    return (
      <span
        className={cn(
          'inline-block rounded border bg-gray-100 text-gray-700 border-gray-300',
          size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs',
          className,
        )}
      >
        {cellId}
      </span>
    )
  }
  const [risk, horizon] = split
  const sizeClasses =
    size === 'sm'
      ? 'px-1.5 py-0.5 text-[10px]'
      : size === 'lg'
      ? 'px-3 py-1 text-sm'
      : 'px-2 py-0.5 text-xs'

  const Component = onClick ? 'button' : 'span'

  return (
    <Component
      onClick={onClick}
      type={onClick ? 'button' : undefined}
      className={cn(
        'inline-flex items-center gap-1 rounded font-medium tracking-tight',
        sizeClasses,
        RISK_STYLES[risk],
        HORIZON_STYLES[horizon],
        selected && 'ring-2 ring-offset-1 ring-current',
        onClick && 'cursor-pointer hover:brightness-95 transition',
        className,
      )}
      title={cellId.replace(/_/g, ' ')}
    >
      <span className="font-semibold">{RISK_LABELS[risk]}</span>
      <span className="opacity-70">·</span>
      <span>{HORIZON_LABELS[horizon]}</span>
    </Component>
  )
}
