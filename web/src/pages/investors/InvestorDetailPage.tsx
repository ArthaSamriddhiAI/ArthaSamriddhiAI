import { Link, useParams } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'

import { useInvestor } from '../../api/investors'
import { cn } from '../../lib/cn'

import { InvestorProfileCard } from './components/InvestorProfileCard'

// Per chunk plan §scope_in:
// "Investor profile detail page at /app/advisor/investors/{investor_id}:
//  Full profile display. Edit button (deferred functionality; cluster 1
//  ships read-only profile detail)."

export function InvestorDetailPage() {
  const { investorId } = useParams({ from: '/investors/$investorId' })
  const { data, isLoading, error } = useInvestor(investorId)

  return (
    <div className="p-8 max-w-5xl">
      <Link
        to="/investors"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to investors
      </Link>

      {isLoading && <p className="text-sm text-gray-500">Loading investor…</p>}
      {error && (
        <p className="text-sm text-red-600">
          {error instanceof Error ? error.message : 'Could not load investor.'}
        </p>
      )}
      {data && (
        <>
          <div className="mb-6">
            <h1 className="text-2xl font-semibold text-gray-900">{data.name}</h1>
            <p className="text-sm text-gray-500 mt-1">
              PAN <span className="font-mono">{data.pan}</span>
              <span className="mx-2 text-gray-300">·</span>
              {data.email}
            </p>
          </div>
          <InvestorProfileCard investor={data} />
          <div className="mt-6">
            <button
              type="button"
              disabled
              title="Edit functionality is deferred; cluster 1 ships read-only profile detail"
              className={cn(
                'rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-400',
                'cursor-not-allowed opacity-60',
              )}
            >
              Edit (coming soon)
            </button>
          </div>
        </>
      )}
    </div>
  )
}
