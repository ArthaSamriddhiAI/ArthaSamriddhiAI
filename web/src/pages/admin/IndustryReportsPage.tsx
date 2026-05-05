import { Link } from '@tanstack/react-router'
import { ArrowLeft, Loader2 } from 'lucide-react'

import { type IndustryOutlook, useIndustryReports } from '../../api/industry'
import { cn } from '../../lib/cn'

const OUTLOOK_STYLES: Record<IndustryOutlook, string> = {
  positive: 'bg-green-100 text-green-800 ring-1 ring-green-300',
  neutral: 'bg-gray-100 text-gray-800 ring-1 ring-gray-300',
  negative: 'bg-red-100 text-red-800 ring-1 ring-red-300',
}

export function IndustryReportsPage() {
  const { data, isLoading, error } = useIndustryReports()

  return (
    <div className="p-8 max-w-6xl">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to admin
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">
        Industry Reports
      </h1>
      <p className="text-sm text-gray-600 mb-6">
        Sector outlook with key themes, drivers, and risks. Newest first.
      </p>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      )}

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error.message}
        </div>
      )}

      {data && data.reports.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
          No industry reports loaded yet.
        </div>
      )}

      {data && data.reports.length > 0 && (
        <div className="space-y-3">
          {data.reports.map((r) => (
            <div
              key={r.industry_report_id}
              className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
            >
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    {r.industry_name}
                  </div>
                  <div className="text-xs text-gray-500">
                    {r.industry_code} · {r.report_period} ·{' '}
                    {new Date(r.report_date).toLocaleDateString()}
                  </div>
                </div>
                <span
                  className={cn(
                    'inline-block rounded px-2 py-0.5 text-xs font-medium',
                    OUTLOOK_STYLES[r.outlook],
                  )}
                >
                  {r.outlook}
                </span>
              </div>
              <p className="text-sm text-gray-700 mb-2">{r.summary}</p>
              <ListBlock label="Drivers" items={r.drivers} />
              <ListBlock label="Risks" items={r.risks} />
              <ListBlock label="Themes" items={r.key_themes} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ListBlock({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div className="mt-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
        {label}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={item}
            className="inline-block rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}
