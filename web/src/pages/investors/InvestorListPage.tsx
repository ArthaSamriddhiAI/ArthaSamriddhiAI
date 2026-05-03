import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'

import { useInvestorsList, type Investor } from '../../api/investors'
import { cn } from '../../lib/cn'

import { LifeStageBadge, LiquidityTierBadge } from './components/EnrichmentBadges'

// Per chunk plan §scope_in:
// "Investor list UI at /app/advisor/investors: Table or card layout listing
//  the advisor's investors. Columns: name, PAN, life_stage badge,
//  liquidity_tier badge, age, household, created_at."

export function InvestorListPage() {
  const { data, isLoading, error } = useInvestorsList()

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Investors</h1>
          <p className="text-sm text-gray-500 mt-1">
            {data ? `${data.length} investor${data.length === 1 ? '' : 's'} in your book` : ''}
          </p>
        </div>
        <Link
          to="/investors/new"
          className={cn(
            'inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90',
          )}
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          <Plus size={16} aria-hidden="true" />
          Add New Investor
        </Link>
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading investors…</p>}
      {error && (
        <p className="text-sm text-red-600">
          Could not load investors: {error instanceof Error ? error.message : 'unknown error'}
        </p>
      )}
      {data && data.length === 0 && <EmptyState />}
      {data && data.length > 0 && <InvestorsTable investors={data} />}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
      <h3 className="text-base font-medium text-gray-900 mb-2">No investors yet</h3>
      <p className="text-sm text-gray-500 mb-4">
        Add your first investor to start building your book.
      </p>
      <Link
        to="/investors/new"
        className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white"
        style={{ backgroundColor: 'var(--color-primary)' }}
      >
        <Plus size={16} aria-hidden="true" />
        Add New Investor
      </Link>
    </div>
  )
}

function InvestorsTable({ investors }: { investors: Investor[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Name</th>
            <th className="px-4 py-3 text-left font-medium">PAN</th>
            <th className="px-4 py-3 text-left font-medium">Age</th>
            <th className="px-4 py-3 text-left font-medium">Life Stage</th>
            <th className="px-4 py-3 text-left font-medium">Liquidity Tier</th>
            <th className="px-4 py-3 text-left font-medium">Created</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {investors.map((inv) => (
            <tr key={inv.investor_id} className="hover:bg-gray-50 transition-colors">
              <td className="px-4 py-3">
                <Link
                  to="/investors/$investorId"
                  params={{ investorId: inv.investor_id }}
                  className="font-medium text-gray-900 hover:underline"
                  style={{ color: 'var(--color-primary)' }}
                >
                  {inv.name}
                </Link>
                <div className="text-xs text-gray-500">{inv.email}</div>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-gray-700">{inv.pan}</td>
              <td className="px-4 py-3 text-gray-700">{inv.age}</td>
              <td className="px-4 py-3">
                <LifeStageBadge
                  lifeStage={inv.life_stage}
                  confidence={inv.life_stage_confidence}
                />
              </td>
              <td className="px-4 py-3">
                <LiquidityTierBadge
                  tier={inv.liquidity_tier}
                  range={inv.liquidity_tier_range}
                />
              </td>
              <td className="px-4 py-3 text-xs text-gray-500">
                {new Date(inv.created_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
