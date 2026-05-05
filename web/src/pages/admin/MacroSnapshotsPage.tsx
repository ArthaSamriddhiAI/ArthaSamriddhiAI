import { Link } from '@tanstack/react-router'
import { ArrowLeft, Loader2 } from 'lucide-react'

import { useMacroSnapshots } from '../../api/macro'

export function MacroSnapshotsPage() {
  const { data, isLoading, error } = useMacroSnapshots()

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
        Macro Snapshots
      </h1>
      <p className="text-sm text-gray-600 mb-6">
        India macroeconomic indicators by period. Newest first.
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

      {data && data.snapshots.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
          No macro snapshots loaded yet.
        </div>
      )}

      {data && data.snapshots.length > 0 && (
        <div className="space-y-3">
          {data.snapshots.map((s) => (
            <div
              key={s.macro_snapshot_id}
              className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-semibold text-gray-900">
                  {s.country_code} · {s.snapshot_period}
                </div>
                <div className="text-xs text-gray-500">
                  {new Date(s.snapshot_date).toLocaleDateString()}
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <Indicator label="GDP growth" value={s.gdp_growth_pct} suffix="%" />
                <Indicator label="CPI" value={s.cpi_inflation_pct} suffix="%" />
                <Indicator label="Repo" value={s.repo_rate_pct} suffix="%" />
                <Indicator label="10y yield" value={s.bond_yield_10y_pct} suffix="%" />
                <Indicator label="USD/INR" value={s.fx_usd_inr} />
                <Indicator label="WPI" value={s.wpi_inflation_pct} suffix="%" />
                <Indicator label="Reverse repo" value={s.reverse_repo_rate_pct} suffix="%" />
                <Indicator label="Unemployment" value={s.unemployment_rate_pct} suffix="%" />
              </div>
              {s.themes.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {s.themes.map((t) => (
                    <span
                      key={t}
                      className="inline-block rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Indicator({
  label,
  value,
  suffix,
}: {
  label: string
  value: number | null
  suffix?: string
}) {
  return (
    <div>
      <div className="text-gray-500 text-[10px] uppercase tracking-wider">
        {label}
      </div>
      <div className="font-mono text-gray-900">
        {value !== null ? value : '—'}
        {value !== null && suffix ? suffix : ''}
      </div>
    </div>
  )
}
