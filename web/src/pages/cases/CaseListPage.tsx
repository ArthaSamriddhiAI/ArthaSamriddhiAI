import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import {
  useCasesList,
  type CaseMode,
  type CaseStatus,
} from '../../api/cases'

import { StatusPill } from './components/StatusPill'

// Per chunk 5.5 plan: list of cases visible to the actor (advisor: own
// book; CIO + compliance + audit: firm-wide). Filters: status, case_mode.
// Click a row to open the case detail page.

const STATUS_OPTIONS: Array<{ value: CaseStatus | ''; label: string }> = [
  { value: '', label: 'All' },
  { value: 'gathering_evidence', label: 'Gathering Evidence' },
  { value: 'synthesizing', label: 'Synthesizing' },
  { value: 'awaiting_committee', label: 'Awaiting Committee' },
  { value: 'awaiting_governance', label: 'Awaiting Governance' },
  { value: 'awaiting_challenge', label: 'Awaiting Challenge' },
  { value: 'awaiting_decision', label: 'Awaiting Decision' },
  { value: 'decided', label: 'Decided' },
  { value: 'failed', label: 'Failed' },
  { value: 'archived', label: 'Archived' },
]

const MODE_OPTIONS: Array<{ value: CaseMode | ''; label: string }> = [
  { value: '', label: 'All' },
  { value: 'proposed_action', label: 'Proposed Action' },
  { value: 'scenario', label: 'Scenario' },
  { value: 'diagnostic', label: 'Diagnostic' },
  { value: 'briefing', label: 'Briefing' },
]

export function CaseListPage() {
  const [statusFilter, setStatusFilter] = useState<CaseStatus | ''>('')
  const [modeFilter, setModeFilter] = useState<CaseMode | ''>('')

  const { data, isLoading, error } = useCasesList({
    status: statusFilter || undefined,
    case_mode: modeFilter || undefined,
  })

  return (
    <div className="p-8 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Cases</h1>
        <p className="text-sm text-gray-500 mt-1">
          {data ? `${data.total} case${data.total === 1 ? '' : 's'}` : ''}
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <FilterSelect
          label="Status"
          value={statusFilter}
          options={STATUS_OPTIONS}
          onChange={(v) => setStatusFilter(v as CaseStatus | '')}
        />
        <FilterSelect
          label="Mode"
          value={modeFilter}
          options={MODE_OPTIONS}
          onChange={(v) => setModeFilter(v as CaseMode | '')}
        />
        {(statusFilter || modeFilter) && (
          <button
            type="button"
            onClick={() => {
              setStatusFilter('')
              setModeFilter('')
            }}
            className="text-sm text-gray-600 underline hover:text-gray-900"
          >
            Clear filters
          </button>
        )}
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading cases…</p>}
      {error && (
        <p className="text-sm text-red-600">
          Could not load cases: {error instanceof Error ? error.message : 'unknown'}
        </p>
      )}
      {data && data.cases.length === 0 && <EmptyState />}
      {data && data.cases.length > 0 && <CasesTable cases={data.cases} />}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
      <h3 className="text-base font-medium text-gray-900 mb-2">No cases yet</h3>
      <p className="text-sm text-gray-500">
        Open a case from an investor's profile to start the reasoning pipeline.
      </p>
    </div>
  )
}

interface FilterProps<T extends string> {
  label: string
  value: T | ''
  options: Array<{ value: T | ''; label: string }>
  onChange: (v: string) => void
}

function FilterSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: FilterProps<T>) {
  return (
    <label className="flex flex-col text-xs font-medium text-gray-600">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function CasesTable({ cases }: { cases: import('../../api/cases').Case[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Case ID</th>
            <th className="px-4 py-3 text-left font-medium">Mode</th>
            <th className="px-4 py-3 text-left font-medium">Intent</th>
            <th className="px-4 py-3 text-left font-medium">Status</th>
            <th className="px-4 py-3 text-left font-medium">Investor</th>
            <th className="px-4 py-3 text-left font-medium">Assigned to</th>
            <th className="px-4 py-3 text-left font-medium">Created</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {cases.map((c) => (
            <tr key={c.case_id} className="hover:bg-gray-50">
              <td className="px-4 py-3 font-mono text-xs text-gray-600">
                <Link
                  to="/cases/$caseId"
                  params={{ caseId: c.case_id }}
                  className="text-blue-600 hover:underline"
                >
                  {c.case_id.slice(0, 8)}…
                </Link>
              </td>
              <td className="px-4 py-3 text-gray-700">
                {c.case_mode.replace('_', ' ')}
              </td>
              <td className="px-4 py-3 text-gray-700">{c.case_intent ?? '—'}</td>
              <td className="px-4 py-3">
                <StatusPill status={c.status} />
              </td>
              <td className="px-4 py-3 font-mono text-xs text-gray-500">
                {c.investor_id.slice(0, 8)}…
              </td>
              <td className="px-4 py-3 text-gray-700">{c.assigned_to}</td>
              <td className="px-4 py-3 text-gray-500">
                {new Date(c.created_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
