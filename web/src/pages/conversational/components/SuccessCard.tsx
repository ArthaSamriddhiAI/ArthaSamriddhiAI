import { Link } from '@tanstack/react-router'
import { CheckCircle2 } from 'lucide-react'

import type { Investor } from '../../../api/investors'
import { InvestorProfileCard } from '../../investors/components/InvestorProfileCard'

// Per FR Entry 14.0 §4.2 — STATE_COMPLETED renders as a card showing the
// enriched investor profile, with a "View Investor" CTA. Reuses the same
// :class:`InvestorProfileCard` that the form path renders inline — visual
// parity is the explicit goal (chunk plan §implementation_notes).

export function SuccessCard({ investor }: { investor: Investor }) {
  return (
    <div className="rounded-lg border-2 border-green-200 bg-green-50 p-5 shadow-sm">
      <div className="flex items-start gap-2 mb-3">
        <CheckCircle2 size={18} className="text-green-700 mt-0.5" />
        <div>
          <h3 className="text-sm font-semibold text-green-900">
            Onboarded {investor.name}
          </h3>
          <p className="text-xs text-green-800">
            The investor record is created and enriched.
          </p>
        </div>
      </div>
      <InvestorProfileCard investor={investor} />
      <div className="mt-4">
        <Link
          to="/investors/$investorId"
          params={{ investorId: investor.investor_id }}
          className="inline-flex items-center rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm"
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          View investor profile
        </Link>
      </div>
    </div>
  )
}
