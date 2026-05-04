import { Loader2 } from 'lucide-react'

import {
  type ConversationRead,
  useCancelConversation,
  useConfirmAction,
} from '../../../api/conversations'
import { cn } from '../../../lib/cn'

// Per FR Entry 14.0 §4.2 — STATE_AWAITING_CONFIRMATION renders as a card
// with all collected slots and Confirm / Edit buttons. Cluster 1 ships a
// "Cancel" path instead of a true edit (per chunk plan §scope_out: "edit
// during STATE_AWAITING_CONFIRMATION ... but not after"; the simplest
// implementation is to cancel and start fresh — which the demo-stage
// addendum §1.5 explicitly accepts).

const SLOT_LABELS: Array<[label: string, key: string]> = [
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

  const slots = conversation.collected_slots
  const householdLabel =
    typeof slots.household_id === 'string' && slots.household_id
      ? `Existing (${slots.household_id})`
      : typeof slots.household_name === 'string' && slots.household_name
        ? `New (${slots.household_name})`
        : '—'

  return (
    <div className="rounded-lg border-2 border-blue-200 bg-blue-50 p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-blue-900 mb-3">
        Confirm and create the investor record
      </h3>
      <dl className="grid grid-cols-2 gap-y-2 text-sm">
        {SLOT_LABELS.map(([label, key]) => {
          const v = slots[key]
          if (v === undefined || v === null || v === '') return null
          return (
            <FragmentRow key={key} label={label} value={String(v)} />
          )
        })}
        <FragmentRow label="Household" value={householdLabel} />
      </dl>

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


function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-blue-900/70">{label}</dt>
      <dd className="text-blue-950 font-medium">{value}</dd>
    </>
  )
}
