import type { MandateVersion } from '../../../api/mandates'
import { cn } from '../../../lib/cn'

// Read-only structured display of a :class:`MandateVersion`'s constraints.
// Reused on the investor profile (Mandate section) and chunk 2.3's
// amendment review surface (each side of the diff).
//
// Per FR Entry 12.1, five constraint families show as labelled groups in
// the same order the form collects them:
//   1. Asset allocation bands
//   2. Single-position concentration
//   3. Liquidity floor
//   4. Sector cap
//   5. Prohibited instruments

export function MandateSummaryCard({
  version,
  highlightFields = new Set<string>(),
  title,
}: {
  version: MandateVersion
  /** Field names to render with a "modified" badge — used by the amendment editor. */
  highlightFields?: Set<string>
  title?: string
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      {title && (
        <div className="text-sm font-semibold text-gray-900 mb-3">{title}</div>
      )}
      <Section title="Asset Allocation">
        <BandRow
          label="Equity"
          min={version.equity_min_pct}
          max={version.equity_max_pct}
          modified={
            highlightFields.has('equity_min_pct')
            || highlightFields.has('equity_max_pct')
          }
        />
        <BandRow
          label="Debt"
          min={version.debt_min_pct}
          max={version.debt_max_pct}
          modified={
            highlightFields.has('debt_min_pct')
            || highlightFields.has('debt_max_pct')
          }
        />
        <BandRow
          label="Cash"
          min={version.cash_min_pct}
          max={version.cash_max_pct}
          modified={
            highlightFields.has('cash_min_pct')
            || highlightFields.has('cash_max_pct')
          }
        />
        <BandRow
          label="Alternatives"
          min={version.alternatives_min_pct}
          max={version.alternatives_max_pct}
          modified={
            highlightFields.has('alternatives_min_pct')
            || highlightFields.has('alternatives_max_pct')
          }
        />
      </Section>

      <Section title="Single-Position Concentration">
        <SingleValueRow
          label="Max per position"
          value={`${version.single_position_max_pct}%`}
          modified={highlightFields.has('single_position_max_pct')}
        />
      </Section>

      <Section title="Liquidity Floor">
        <SingleValueRow
          label="Minimum liquid"
          value={`${version.liquidity_floor_pct}%`}
          modified={highlightFields.has('liquidity_floor_pct')}
        />
      </Section>

      <Section title="Sector Cap">
        <SingleValueRow
          label="Max per sector"
          value={`${version.sector_max_pct}%`}
          modified={highlightFields.has('sector_max_pct')}
        />
      </Section>

      <Section title="Prohibited Instruments">
        {version.prohibited_instruments.length === 0 ? (
          <div className="text-xs text-gray-500">None</div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {version.prohibited_instruments.map((p) => (
              <span
                key={p}
                className={cn(
                  'inline-block rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-700',
                  highlightFields.has(`prohibited:${p}`)
                    && 'bg-yellow-100 text-yellow-900 ring-1 ring-yellow-300',
                )}
              >
                {p}
              </span>
            ))}
          </div>
        )}
      </Section>

      <div className="mt-3 text-xs text-gray-500">
        Version {version.version_number} · Status: {version.status} · Created{' '}
        {new Date(version.created_at).toLocaleDateString()} via {version.created_via}
      </div>
    </div>
  )
}


function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="mb-4 last:mb-0">
      <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-1">
        {title}
      </div>
      {children}
    </div>
  )
}


function BandRow({
  label,
  min,
  max,
  modified,
}: {
  label: string
  min: number
  max: number
  modified?: boolean
}) {
  return (
    <div className="flex items-center justify-between text-sm py-0.5">
      <span className="text-gray-700">{label}</span>
      <span
        className={cn(
          'font-mono text-gray-900',
          modified && 'inline-block rounded bg-yellow-100 px-1.5 ring-1 ring-yellow-300',
        )}
      >
        {min}% - {max}%
      </span>
    </div>
  )
}


function SingleValueRow({
  label,
  value,
  modified,
}: {
  label: string
  value: string
  modified?: boolean
}) {
  return (
    <div className="flex items-center justify-between text-sm py-0.5">
      <span className="text-gray-700">{label}</span>
      <span
        className={cn(
          'font-mono text-gray-900',
          modified && 'inline-block rounded bg-yellow-100 px-1.5 ring-1 ring-yellow-300',
        )}
      >
        {value}
      </span>
    </div>
  )
}
