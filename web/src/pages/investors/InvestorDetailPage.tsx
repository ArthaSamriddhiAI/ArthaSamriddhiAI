import { Link, useParams } from '@tanstack/react-router'
import { ArrowLeft, Plus } from 'lucide-react'

import { useInvestor } from '../../api/investors'
import { useActiveMandate } from '../../api/mandates'
import { cn } from '../../lib/cn'
import { MandateSummaryCard } from '../mandates/components/MandateSummaryCard'

import { InvestorProfileCard } from './components/InvestorProfileCard'

// Per chunk plan §scope_in (cluster 1):
//   "Investor profile detail page at /app/advisor/investors/{investor_id}:
//    Full profile display. Edit button (deferred functionality; cluster 1
//    ships read-only profile detail)."
//
// Cluster 2 chunk 2.1 §scope_in adds:
//   "The investor profile detail page (cluster 1) gains a 'Mandate'
//    section showing the active mandate's constraints in a read-only
//    summary view. 'Amend Mandate' button visible. 'Create Mandate'
//    button visible when no mandate exists yet."

export function InvestorDetailPage() {
  const { investorId } = useParams({ from: '/investors/$investorId' })
  const { data, isLoading, error } = useInvestor(investorId)
  const mandateQuery = useActiveMandate(investorId)

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

          {/* Mandate section — chunk 2.1 §scope_in */}
          <section className="mt-8">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-semibold text-gray-900">
                Investment Mandate
              </h2>
              {mandateQuery.data?.active_version ? (
                <Link
                  to="/investors/$investorId/mandate/amend"
                  params={{ investorId }}
                  className={cn(
                    'rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs',
                    'font-medium text-gray-700 hover:bg-gray-50',
                  )}
                >
                  Amend Mandate
                </Link>
              ) : (
                <Link
                  to="/investors/$investorId/mandate/new"
                  params={{ investorId }}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs',
                    'font-medium text-white shadow-sm',
                  )}
                  style={{ backgroundColor: 'var(--color-primary)' }}
                >
                  <Plus size={12} />
                  Create Mandate
                </Link>
              )}
            </div>
            {mandateQuery.isLoading && (
              <p className="text-sm text-gray-500">Loading mandate…</p>
            )}
            {!mandateQuery.isLoading && !mandateQuery.data && (
              <div className="rounded-md border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
                No mandate yet. Click "Create Mandate" to set the investor's
                investment policy constraints.
              </div>
            )}
            {mandateQuery.data?.active_version && (
              <MandateSummaryCard version={mandateQuery.data.active_version} />
            )}
          </section>

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
