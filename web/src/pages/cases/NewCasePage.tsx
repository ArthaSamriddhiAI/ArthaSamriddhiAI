import { useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'

import {
  CASE_INTENT_OPTIONS,
  CASE_MODE_OPTIONS,
  useCreateCase,
  type CaseIntent,
  type CaseMode,
} from '../../api/cases'
import { useInvestorsList } from '../../api/investors'

// Per chunk 5.5: simple form to open a new case. Investor pre-selected
// when arriving from the investor profile linkage card (search param
// ``investorId``); otherwise advisor picks from their list.

export function NewCasePage() {
  const search = useSearch({ strict: false }) as { investorId?: string }
  const navigate = useNavigate()
  const investors = useInvestorsList()

  const [investorId, setInvestorId] = useState<string>(search.investorId ?? '')
  const [caseMode, setCaseMode] = useState<CaseMode>('proposed_action')
  const [caseIntent, setCaseIntent] = useState<CaseIntent | ''>('')
  const [proposedAction, setProposedAction] = useState('')
  const [proposedAmount, setProposedAmount] = useState('')
  const [products, setProducts] = useState('')
  const [materialityFlag, setMaterialityFlag] = useState(false)

  const mutation = useCreateCase()

  // Filter intents by mode.
  const eligibleIntents = CASE_INTENT_OPTIONS.filter((o) =>
    o.modes.includes(caseMode),
  )

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!investorId) return
    mutation.mutate(
      {
        investor_id: investorId,
        case_mode: caseMode,
        case_intent: caseIntent || undefined,
        proposed_action: proposedAction.trim() || undefined,
        proposed_action_amount_inr: proposedAmount.trim() || undefined,
        proposed_action_products: products
          .split(',')
          .map((p) => p.trim())
          .filter(Boolean),
        materiality_manual_flag: materialityFlag,
      },
      {
        onSuccess: (created) => {
          navigate({ to: '/cases/$caseId', params: { caseId: created.case_id } })
        },
      },
    )
  }

  return (
    <div className="p-8 max-w-2xl">
      <h1 className="mb-1 text-2xl font-semibold text-gray-900">Open new case</h1>
      <p className="mb-6 text-sm text-gray-500">
        The reasoning pipeline runs end-to-end on submit. Proposed_action
        and scenario cases pause at <em>awaiting_decision</em>; diagnostic
        and briefing cases auto-decide.
      </p>

      <form
        onSubmit={onSubmit}
        className="space-y-4 rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
      >
        <label className="block">
          <span className="text-xs font-medium text-gray-600">
            Investor <span className="text-red-600">*</span>
          </span>
          <select
            value={investorId}
            onChange={(e) => setInvestorId(e.target.value)}
            required
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">Select an investor…</option>
            {investors.data?.map((inv) => (
              <option key={inv.investor_id} value={inv.investor_id}>
                {inv.name} · {inv.pan}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-medium text-gray-600">
            Case mode <span className="text-red-600">*</span>
          </span>
          <select
            value={caseMode}
            onChange={(e) => {
              const next = e.target.value as CaseMode
              setCaseMode(next)
              setCaseIntent('')
            }}
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {CASE_MODE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-medium text-gray-600">Intent</span>
          <select
            value={caseIntent}
            onChange={(e) => setCaseIntent(e.target.value as CaseIntent | '')}
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">— Pick an intent —</option>
            {eligibleIntents.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        {(caseMode === 'proposed_action' || caseMode === 'scenario') && (
          <>
            <label className="block">
              <span className="text-xs font-medium text-gray-600">
                Proposed action
              </span>
              <textarea
                value={proposedAction}
                onChange={(e) => setProposedAction(e.target.value)}
                rows={2}
                className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder="e.g. Shift 10% from equity to debt"
              />
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-600">
                  Amount (INR)
                </span>
                <input
                  type="number"
                  min="0"
                  value={proposedAmount}
                  onChange={(e) => setProposedAmount(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600">
                  Products (comma-separated)
                </span>
                <input
                  type="text"
                  value={products}
                  onChange={(e) => setProducts(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  placeholder="pms, aif, mutual_fund"
                />
              </label>
            </div>

            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={materialityFlag}
                onChange={(e) => setMaterialityFlag(e.target.checked)}
                className="mt-0.5"
              />
              <span className="text-sm text-gray-700">
                Force materiality (sends to IC1 regardless of rule
                triggers)
              </span>
            </label>
          </>
        )}

        {mutation.error && (
          <p className="text-sm text-red-600">
            {mutation.error instanceof Error
              ? mutation.error.message
              : 'unknown error'}
          </p>
        )}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={mutation.isPending || !investorId}
            className="inline-flex items-center rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {mutation.isPending ? 'Opening case…' : 'Open Case'}
          </button>
          <button
            type="button"
            onClick={() => navigate({ to: '/cases' })}
            className="text-sm text-gray-600 underline hover:text-gray-900"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
