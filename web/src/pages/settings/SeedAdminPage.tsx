import { AlertTriangle, Database, Loader2, RotateCcw, Upload } from 'lucide-react'
import { useState } from 'react'

import {
  useLoadSeed,
  useResetSeed,
  useSeedStatus,
} from '../../api/seed'

// Per chunk 5.6 §5.6.5: CIO-only settings panel for the demo seed
// framework. Lists current seed-row counts + Load + Reset buttons.
// Shape modelled on the LLM router settings page so the navigation
// feels familiar.

export function SeedAdminPage() {
  const status = useSeedStatus()
  const load = useLoadSeed()
  const reset = useResetSeed()
  const [confirmReset, setConfirmReset] = useState(false)

  if (status.isLoading) {
    return (
      <div className="p-8 max-w-3xl flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin" /> Loading seed status…
      </div>
    )
  }

  if (status.error) {
    return (
      <div className="p-8 max-w-3xl">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load seed status:{' '}
          {status.error instanceof Error ? status.error.message : ''}
        </div>
      </div>
    )
  }

  const counts = status.data?.counts ?? {
    investors: 0,
    households: 0,
    mandates: 0,
    cases: 0,
  }
  const isLoaded = status.data?.is_loaded ?? false

  return (
    <div className="p-8 max-w-3xl space-y-6">
      <header className="flex items-start gap-3">
        <Database
          size={28}
          className="mt-1 text-gray-700"
          aria-hidden="true"
        />
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Demo Seed</h1>
          <p className="mt-1 text-sm text-gray-600">
            Load or reset the cluster-5 demo cohort: 7 households, 15
            archetype investors, 15 mandates, ~12 representative cases
            spanning every case mode + materiality outcome. Cases run
            through the same chunk-5.4 pipeline as live cases — the
            rows are tagged{' '}
            <code className="rounded bg-gray-100 px-1 text-xs">is_seed_data=True</code>{' '}
            so reset can wipe them cleanly.
          </p>
        </div>
      </header>

      <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">
          Current state
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Counter label="Households" value={counts.households} />
          <Counter label="Investors" value={counts.investors} />
          <Counter label="Mandates" value={counts.mandates} />
          <Counter label="Cases" value={counts.cases} />
        </div>
        <p className="mt-3 text-xs text-gray-500">
          {isLoaded ? (
            <>
              Seed cohort is currently loaded. Reset before reloading.
            </>
          ) : (
            <>No seed rows present. Click Load to populate the demo cohort.</>
          )}
        </p>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Actions</h2>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => load.mutate()}
            disabled={isLoaded || load.isPending}
            className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {load.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Upload size={14} />
            )}
            {load.isPending ? 'Loading seed…' : 'Load seed'}
          </button>

          {confirmReset ? (
            <div className="flex items-center gap-2">
              <span className="text-sm text-rose-700">
                Confirm wipe of every seed row?
              </span>
              <button
                type="button"
                onClick={() => {
                  reset.mutate()
                  setConfirmReset(false)
                }}
                disabled={reset.isPending}
                className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700"
              >
                {reset.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <RotateCcw size={14} />
                )}
                Yes, reset
              </button>
              <button
                type="button"
                onClick={() => setConfirmReset(false)}
                className="text-sm text-gray-600 underline hover:text-gray-900"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmReset(true)}
              disabled={!isLoaded || reset.isPending}
              className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 shadow-sm hover:bg-gray-50 disabled:opacity-50"
            >
              <RotateCcw size={14} />
              Reset
            </button>
          )}
        </div>

        {load.error && (
          <p className="mt-3 text-sm text-red-600">
            {load.error instanceof Error ? load.error.message : 'Load failed.'}
          </p>
        )}
        {reset.error && (
          <p className="mt-3 text-sm text-red-600">
            {reset.error instanceof Error ? reset.error.message : 'Reset failed.'}
          </p>
        )}
        {load.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700">
            Loaded {load.data.households} households, {load.data.investors}{' '}
            investors, {load.data.mandates} mandates, {load.data.cases} cases.
          </p>
        )}
        {reset.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700">
            Reset complete: {reset.data.cases_deleted} cases,{' '}
            {reset.data.investors_deleted} investors,{' '}
            {reset.data.households_deleted} households,{' '}
            {reset.data.stage_rows_deleted} stage rows scrubbed.
          </p>
        )}
      </section>

      <section className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <div className="flex items-start gap-2">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-medium">Privileged operation</p>
            <p className="mt-1 text-xs">
              Seed admin is restricted to the CIO role per FR 19.0 §3.2.
              Production deployments should disable this surface entirely
              once real client data is loaded.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}

function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-gray-100 bg-gray-50 px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-gray-900">{value}</div>
    </div>
  )
}
