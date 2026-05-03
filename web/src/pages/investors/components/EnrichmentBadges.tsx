import { cn } from '../../../lib/cn'

// Display labels mirroring src/artha/api_v2/i0/active_layer.py LIFE_STAGE_LABELS
// and LIQUIDITY_TIER_LABELS. Tooltips reflect FR 11.1 §2.3 and §3.3.

const LIFE_STAGE_LABELS: Record<string, string> = {
  accumulation: 'Wealth Building',
  transition: 'Wealth Transition',
  distribution: 'Income Generation',
  legacy: 'Estate Planning',
}

const LIFE_STAGE_TOOLTIPS: Record<string, string> = {
  accumulation:
    'Investor is building wealth toward future goals; investment focus is growth-oriented with longer time horizons.',
  transition:
    'Investor is approaching a life transition (retirement, major expense, business sale, etc.); investment focus balances growth and preservation.',
  distribution:
    'Investor is drawing on accumulated wealth for current needs; investment focus prioritises stable income and preservation.',
  legacy:
    'Investor is focused on long-term wealth transfer to next generations; investment focus includes tax efficiency and inter-generational considerations.',
}

const LIQUIDITY_TIER_LABELS: Record<string, string> = {
  essential: 'Minimum Liquidity',
  secondary: 'Moderate Liquidity',
  deep: 'High Liquidity',
}

const LIQUIDITY_TIER_TOOLTIPS: Record<string, string> = {
  essential:
    'Investor has long horizons and growth-oriented risk appetite; most assets in growth instruments. Reserve for emergencies and tactical opportunities.',
  secondary:
    'Investor balances growth with the need for accessible reserves. Reserve covers transitional needs and provides flexibility.',
  deep: 'Investor has significant near-term needs or conservative profile requiring substantial accessible reserves.',
}

interface LifeStageBadgeProps {
  lifeStage: string | null
  confidence?: string | null
}

export function LifeStageBadge({ lifeStage, confidence }: LifeStageBadgeProps) {
  if (!lifeStage) return null
  const label = LIFE_STAGE_LABELS[lifeStage] ?? lifeStage
  const tooltip = LIFE_STAGE_TOOLTIPS[lifeStage] ?? ''
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium text-white',
      )}
      style={{ backgroundColor: 'var(--color-primary)' }}
      title={tooltip}
    >
      <span className="capitalize">{lifeStage}:</span>
      <span>{label}</span>
      {confidence === 'low' && (
        <span
          className="ml-1 rounded-sm bg-white/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wider"
          title="Low confidence — system classification may benefit from advisor review"
        >
          Low conf.
        </span>
      )}
    </span>
  )
}

interface LiquidityTierBadgeProps {
  tier: string | null
  range: string | null
}

export function LiquidityTierBadge({ tier, range }: LiquidityTierBadgeProps) {
  if (!tier) return null
  const label = LIQUIDITY_TIER_LABELS[tier] ?? tier
  const tooltip = LIQUIDITY_TIER_TOOLTIPS[tier] ?? ''
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium text-white',
      )}
      style={{ backgroundColor: 'var(--color-accent)' }}
      title={tooltip}
    >
      <span className="capitalize">{tier}:</span>
      <span>
        {label}
        {range && <span className="ml-1 opacity-80">({range})</span>}
      </span>
    </span>
  )
}
