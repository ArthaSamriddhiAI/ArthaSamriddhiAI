import { Loader2 } from 'lucide-react'

import {
  type ConversationRead,
  useCancelConversation,
  useConfirmAction,
} from '../../../api/conversations'
import { cn } from '../../../lib/cn'

// Per FR Entry 14.0 §4.2 — STATE_AWAITING_CONFIRMATION renders as a card
// with all collected slots and Confirm / Cancel buttons. Cluster 2 chunk
// 2.2 adds the mandate_creation intent variant: same card shape, different
// label set (the five constraint families instead of identity fields).

const ONBOARDING_LABELS: Array<[label: string, key: string]> = [
  ['Name', 'name'],
  ['Email', 'email'],
  ['Phone', 'phone'],
  ['PAN', 'pan'],
  ['Age', 'age'],
  ['Risk appetite', 'risk_appetite'],
  ['Time horizon', 'time_horizon'],
]


export function ConfirmationCard({
  conversation,
}: {
  conversation: ConversationRead
}) {
  const confirmMutation = useConfirmAction(conversation.conversation_id)
  const cancelMutation = useCancelConversation(conversation.conversation_id)

  const isMandate = conversation.intent === 'mandate_creation'

  return (
    <div className="rounded-lg border-2 border-blue-200 bg-blue-50 p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-blue-900 mb-3">
        {isMandate
          ? 'Confirm and create the mandate'
          : 'Confirm and create the investor record'}
      </h3>
      {isMandate ? (
        <MandateSummary conversation={conversation} />
      ) : (
        <OnboardingSummary conversation={conversation} />
      )}

      {confirmMutation.error && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {confirmMutation.error.message}
        </div>
      )}

      <div className="mt-4 flex gap-3">
        <button
          type="button"
          onClick={() => confirmMutation.mutate()}
          disabled={confirmMutation.isPending}
          className={cn(
            'inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm',
            'disabled:cursor-not-allowed disabled:opacity-60',
          )}
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          {confirmMutation.isPending && <Loader2 size={14} className="animate-spin" />}
          {confirmMutation.isPending ? 'Creating…' : 'Confirm and create'}
        </button>
        <button
          type="button"
          onClick={() => cancelMutation.mutate()}
          disabled={cancelMutation.isPending}
          className={cn(
            'rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700',
            'hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60',
          )}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}


function OnboardingSummary({
  conversation,
}: {
  conversation: ConversationRead
}) {
  const slots = conversation.collected_slots
  const householdLabel =
    typeof slots.household_id === 'string' && slots.household_id
      ? `Existing (${slots.household_id})`
      : typeof slots.household_name === 'string' && slots.household_name
        ? `New (${slots.household_name})`
        : '—'
  return (
    <dl className="grid grid-cols-2 gap-y-2 text-sm">
      {ONBOARDING_LABELS.map(([label, key]) => {
        const v = slots[key]
        if (v === undefined || v === null || v === '') return null
        return <FragmentRow key={key} label={label} value={String(v)} />
      })}
      <FragmentRow label="Household" value={householdLabel} />
    </dl>
  )
}


function MandateSummary({
  conversation,
}: {
  conversation: ConversationRead
}) {
  const slots = conversation.collected_slots as Record<string, unknown>
  const investorName = (slots.investor_name as string) || '—'

  const band = (
    minKey: string, maxKey: string,
  ): string => {
    const min = slots[minKey]
    const max = slots[maxKey]
    if (typeof min !== 'number' || typeof max !== 'number') return '—'
    return `${min}% – ${max}%`
  }
  const pct = (key: string): string => {
    const v = slots[key]
    return typeof v === 'number' ? `${v}%` : '—'
  }
  const prohibited = (slots.prohibited_instruments as string[] | undefined) ?? []
  const prohibitedDisplay = prohibited.length === 0 ? 'None' : prohibited.join(', ')

  return (
    <dl className="grid grid-cols-2 gap-y-2 text-sm">
      <FragmentRow label="Investor" value={investorName} />
      <FragmentRow label="Equity" value={band('equity_min_pct', 'equity_max_pct')} />
      <FragmentRow label="Debt" value={band('debt_min_pct', 'debt_max_pct')} />
      <FragmentRow
        label="Alternatives"
        value={band('alternatives_min_pct', 'alternatives_max_pct')}
      />
      <FragmentRow label="Single-position max" value={pct('single_position_max_pct')} />
      <FragmentRow label="Liquidity floor" value={pct('liquidity_floor_pct')} />
      <FragmentRow label="Sector cap" value={pct('sector_max_pct')} />
      <FragmentRow label="Prohibited" value={prohibitedDisplay} />
    </dl>
  )
}


function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-blue-900/70">{label}</dt>
      <dd className="text-blue-950 font-medium">{value}</dd>
    </>
  )
}
