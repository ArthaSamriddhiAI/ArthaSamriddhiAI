import type { Investor } from '../../../api/investors'
import { cn } from '../../../lib/cn'

import { LifeStageBadge, LiquidityTierBadge } from './EnrichmentBadges'

// Two-column profile display per chunk plan §scope_in:
// "Investor profile display component (used by form success state and
//  future investor list detail pages): Two-column layout: entered fields
//  on left, enrichment signals on right."
//
// Used by:
// - InvestorDetailPage (full-page detail)
// - NewInvestorPage success state (inline after form submission)
// - C0 chat success card (chunk 1.2 will reuse)

interface Props {
  investor: Investor
}

export function InvestorProfileCard({ investor }: Props) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm p-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <EnteredFields investor={investor} />
        <EnrichmentSignals investor={investor} />
      </div>
    </div>
  )
}

function EnteredFields({ investor }: { investor: Investor }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
        Entered Fields
      </h3>
      <dl className="space-y-2 text-sm">
        <Row label="Name" value={investor.name} />
        <Row label="Email" value={investor.email} />
        <Row label="Phone" value={investor.phone} />
        <Row label="PAN" value={investor.pan} />
        <Row label="Age" value={String(investor.age)} />
        <Row label="Risk Appetite" value={capitalize(investor.risk_appetite)} />
        <Row label="Time Horizon" value={humanHorizon(investor.time_horizon)} />
        <Row label="KYC Status" value={capitalize(investor.kyc_status)} />
        <Row
          label="Onboarded Via"
          value={capitalize(investor.created_via)}
        />
      </dl>
    </div>
  )
}

function EnrichmentSignals({ investor }: { investor: Investor }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
        I0 Enrichment Signals
      </h3>
      <div className="space-y-3">
        <div>
          <div className="text-xs text-gray-500 mb-1">Life Stage</div>
          {investor.life_stage ? (
            <LifeStageBadge
              lifeStage={investor.life_stage}
              confidence={investor.life_stage_confidence}
            />
          ) : (
            <span className="text-sm text-gray-400">Not yet enriched</span>
          )}
        </div>
        <div>
          <div className="text-xs text-gray-500 mb-1">Liquidity Tier</div>
          {investor.liquidity_tier ? (
            <LiquidityTierBadge
              tier={investor.liquidity_tier}
              range={investor.liquidity_tier_range}
            />
          ) : (
            <span className="text-sm text-gray-400">Not yet enriched</span>
          )}
        </div>
        {investor.enrichment_version && (
          <div className="pt-3 border-t border-gray-100">
            <div className="text-xs text-gray-400">
              Enrichment version:{' '}
              <span className="font-mono">{investor.enrichment_version}</span>
            </div>
            {investor.enriched_at && (
              <div className="text-xs text-gray-400">
                Enriched: {new Date(investor.enriched_at).toLocaleString()}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className={cn('flex justify-between gap-4')}>
      <dt className="text-gray-500 shrink-0">{label}</dt>
      <dd className="text-gray-900 text-right break-all">{value}</dd>
    </div>
  )
}

function capitalize(s: string): string {
  return s.length > 0 ? s[0].toUpperCase() + s.slice(1) : s
}

function humanHorizon(h: string): string {
  return (
    {
      under_3_years: 'Under 3 years',
      '3_to_5_years': '3 to 5 years',
      over_5_years: 'Over 5 years',
    }[h] ?? h
  )
}
