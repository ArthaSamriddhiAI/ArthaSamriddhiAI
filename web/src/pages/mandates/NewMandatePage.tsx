import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { ArrowLeft, FileUp, Loader2, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { z } from 'zod'

import { useInvestor } from '../../api/investors'
import {
  type MandateCreatePayload,
  type MandateDefaults,
  type SoftWarning,
  useCreateMandate,
  useMandateDefaults,
} from '../../api/mandates'
import { cn } from '../../lib/cn'

// Per chunk plan §2.1 §scope_in:
//   "Form UI at /app/advisor/investors/{investor_id}/mandate/new:
//     - Five-section single-page form (Asset Allocation, Single-Position
//       Limit, Liquidity Floor, Sector Cap, Prohibited Instruments).
//     - I0 defaults pre-populated based on investor's risk_appetite and
//       liquidity_tier.
//     - I0 source labels alongside fields.
//     - Field-level validation on blur (client-side).
//     - Cross-constraint validation feedback.
//     - Soft warnings displayed inline.
//     - sessionStorage draft persistence.
//   Plus chunk 2.4 §scope_in:
//     - 'Upload IPS PDF' button visible at the top of the form, disabled,
//       with the appropriate tooltip."

// Zod schema mirrors src/artha/api_v2/m1/schemas.py MandateConstraintInput.
// Per-field range checks; cross-constraint rules (sum-of-mins, max>=min)
// are validated server-side and surfaced via the 400-failures envelope.
const formSchema = z
  .object({
    equity_min_pct: z.number().int().min(0).max(100),
    equity_max_pct: z.number().int().min(0).max(100),
    debt_min_pct: z.number().int().min(0).max(100),
    debt_max_pct: z.number().int().min(0).max(100),
    cash_min_pct: z.number().int().min(0).max(100),
    cash_max_pct: z.number().int().min(0).max(100),
    alternatives_min_pct: z.number().int().min(0).max(100),
    alternatives_max_pct: z.number().int().min(0).max(100),
    single_position_max_pct: z.number().int().min(0).max(100),
    liquidity_floor_pct: z.number().int().min(0).max(100),
    sector_max_pct: z.number().int().min(0).max(100),
    prohibited_instruments: z.array(z.string().min(1).max(200)).max(50),
  })
  .refine((d) => d.equity_max_pct >= d.equity_min_pct, {
    message: 'Equity max must be ≥ equity min',
    path: ['equity_max_pct'],
  })
  .refine((d) => d.debt_max_pct >= d.debt_min_pct, {
    message: 'Debt max must be ≥ debt min',
    path: ['debt_max_pct'],
  })
  .refine((d) => d.cash_max_pct >= d.cash_min_pct, {
    message: 'Cash max must be ≥ cash min',
    path: ['cash_max_pct'],
  })
  .refine((d) => d.alternatives_max_pct >= d.alternatives_min_pct, {
    message: 'Alternatives max must be ≥ alternatives min',
    path: ['alternatives_max_pct'],
  })
  .refine(
    (d) =>
      d.equity_min_pct +
        d.debt_min_pct +
        d.cash_min_pct +
        d.alternatives_min_pct <=
      100,
    {
      message: 'Sum of asset-allocation minimums must be ≤ 100',
      path: ['equity_min_pct'],
    },
  )
  .refine(
    (d) =>
      d.equity_max_pct +
        d.debt_max_pct +
        d.cash_max_pct +
        d.alternatives_max_pct >=
      100,
    {
      message: 'Sum of asset-allocation maximums must be ≥ 100',
      path: ['equity_max_pct'],
    },
  )

type FormValues = z.infer<typeof formSchema>

const DRAFT_KEY_PREFIX = 'cluster-2-new-mandate-draft:'

const I0_SOURCE_LABEL: Record<string, string> = {
  i0_risk_appetite: 'I0 risk_appetite',
  i0_liquidity_tier: 'I0 liquidity_tier',
  industry_standard: 'industry standard',
}


export function NewMandatePage() {
  const { investorId } = useParams({ strict: false }) as { investorId: string }
  const navigate = useNavigate()
  const investorQuery = useInvestor(investorId)
  const defaultsQuery = useMandateDefaults(investorId)
  const createMutation = useCreateMandate(investorId)
  const [serverFailures, setServerFailures] = useState<
    Array<{ field: string; code: string; message: string }> | null
  >(null)

  const draftKey = `${DRAFT_KEY_PREFIX}${investorId}`

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    mode: 'onBlur',
    // Empty defaults; replaced once defaultsQuery resolves OR a stored
    // draft loads from sessionStorage.
    defaultValues: {
      equity_min_pct: 45,
      equity_max_pct: 65,
      debt_min_pct: 15,
      debt_max_pct: 35,
      cash_min_pct: 5,
      cash_max_pct: 15,
      alternatives_min_pct: 5,
      alternatives_max_pct: 15,
      single_position_max_pct: 5,
      liquidity_floor_pct: 20,
      sector_max_pct: 25,
      prohibited_instruments: [],
    },
  })

  // Once defaults arrive, populate the form (unless a stored draft already
  // exists, which we restored on mount).
  useEffect(() => {
    if (!defaultsQuery.data) return
    const stored = sessionStorage.getItem(draftKey)
    if (stored) {
      try {
        form.reset(JSON.parse(stored))
        return
      } catch {
        // ignore corrupt draft and fall through to defaults
      }
    }
    form.reset(defaultsToFormValues(defaultsQuery.data))
  }, [defaultsQuery.data, draftKey, form])

  // Persist drafts as the advisor types.
  useEffect(() => {
    const sub = form.watch((value) => {
      sessionStorage.setItem(draftKey, JSON.stringify(value))
    })
    return () => sub.unsubscribe()
  }, [form, draftKey])

  const onSubmit = (values: FormValues) => {
    const payload: MandateCreatePayload = { ...values }
    setServerFailures(null)
    createMutation.mutate(payload, {
      onSuccess: () => {
        sessionStorage.removeItem(draftKey)
        navigate({
          to: '/investors/$investorId',
          params: { investorId },
        })
      },
      onError: (err) => {
        if (err.status === 400 && err.problem && 'failures' in err.problem) {
          setServerFailures(
            err.problem.failures as Array<{ field: string; code: string; message: string }>,
          )
        }
        if (err.status === 409) {
          // Already exists — bounce back to investor profile.
          navigate({
            to: '/investors/$investorId',
            params: { investorId },
          })
        }
      },
    })
  }

  const investor = investorQuery.data
  const defaults = defaultsQuery.data
  const sources = defaults?.sources ?? {}

  if (investorQuery.isLoading || defaultsQuery.isLoading) {
    return (
      <div className="p-8 max-w-3xl flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin" /> Loading…
      </div>
    )
  }
  if (!investor) {
    return (
      <div className="p-8 max-w-3xl">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Investor not found.
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-3xl">
      <Link
        to="/investors/$investorId"
        params={{ investorId }}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to investor
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-1">
        Create Mandate for {investor.name}
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Five constraint families. I0 defaults are pre-populated; adjust as
        needed. Drafts auto-save to your browser session.
      </p>

      <PdfUploadStub />

      {createMutation.isPending && (
        <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          Creating mandate…
        </div>
      )}

      {serverFailures && serverFailures.length > 0 && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="font-medium mb-1">Server validation failed:</div>
          <ul className="list-disc list-inside">
            {serverFailures.map((f, i) => (
              <li key={i}>{f.message}</li>
            ))}
          </ul>
        </div>
      )}

      <SoftWarningsBanner warnings={createMutation.data?.warnings ?? []} />

      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">
        <Section
          title="Asset Allocation"
          description="Min/max bands for each asset class. Sum of mins ≤ 100; sum of maxes ≥ 100."
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <BandPair
              label="Equity"
              minName="equity_min_pct"
              maxName="equity_max_pct"
              form={form}
              source={sources.equity_min_pct}
            />
            <BandPair
              label="Debt"
              minName="debt_min_pct"
              maxName="debt_max_pct"
              form={form}
              source={sources.debt_min_pct}
            />
            <BandPair
              label="Cash"
              minName="cash_min_pct"
              maxName="cash_max_pct"
              form={form}
              source={sources.cash_min_pct}
            />
            <BandPair
              label="Alternatives"
              minName="alternatives_min_pct"
              maxName="alternatives_max_pct"
              form={form}
              source={sources.alternatives_min_pct}
            />
          </div>
        </Section>

        <Section
          title="Single-Position Concentration"
          description="Maximum percentage of portfolio in any single instrument."
        >
          <PercentInput
            label="Max %"
            name="single_position_max_pct"
            form={form}
            source={sources.single_position_max_pct}
          />
        </Section>

        <Section
          title="Liquidity Floor"
          description="Minimum percentage of portfolio held in highly liquid instruments."
        >
          <PercentInput
            label="Min %"
            name="liquidity_floor_pct"
            form={form}
            source={sources.liquidity_floor_pct}
          />
        </Section>

        <Section
          title="Sector Cap"
          description="Maximum percentage of portfolio in any single GICS sector."
        >
          <PercentInput
            label="Max %"
            name="sector_max_pct"
            form={form}
            source={sources.sector_max_pct}
          />
        </Section>

        <Section
          title="Prohibited Instruments"
          description="Specific instruments, categories, or themes the investor excludes."
        >
          <Controller
            control={form.control}
            name="prohibited_instruments"
            render={({ field }) => (
              <ProhibitedTagsInput
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        </Section>

        <div className="flex justify-end gap-3">
          <Link
            to="/investors/$investorId"
            params={{ investorId }}
            className="rounded-md px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className={cn(
              'rounded-md px-5 py-2 text-sm font-medium text-white shadow-sm',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {createMutation.isPending ? 'Creating…' : 'Create Mandate'}
          </button>
        </div>
      </form>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------


function PdfUploadStub() {
  return (
    <div className="mb-6 rounded-md border border-gray-200 bg-gray-50 p-3 flex items-center gap-3">
      <button
        type="button"
        disabled
        title="PDF parsing coming in production phase. Use the form below for now."
        aria-label="Upload IPS PDF (disabled)"
        className={cn(
          'inline-flex items-center gap-2 rounded-md border border-gray-300',
          'bg-white px-3 py-1.5 text-sm font-medium text-gray-400',
          'cursor-not-allowed opacity-70',
        )}
      >
        <FileUp size={14} aria-hidden="true" />
        Upload IPS PDF
      </button>
      <span className="text-xs text-gray-500">
        PDF parsing coming in production phase. Use the form below for now.
      </span>
    </div>
  )
}


function Section({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <header className="mb-4">
        <h2 className="text-base font-semibold text-gray-900">{title}</h2>
        <p className="text-xs text-gray-500 mt-1">{description}</p>
      </header>
      {children}
    </section>
  )
}


type FormFieldName = keyof FormValues


function PercentInput({
  label,
  name,
  form,
  source,
}: {
  label: string
  name: FormFieldName
  form: ReturnType<typeof useForm<FormValues>>
  source?: string
}) {
  const error = form.formState.errors[name]?.message
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
      </label>
      <input
        type="number"
        min={0}
        max={100}
        {...form.register(name, { valueAsNumber: true })}
        className={cn(
          'w-32 rounded-md border border-gray-300 px-3 py-2 text-sm',
          'focus:outline-none focus:ring-2 focus:ring-offset-1',
        )}
      />
      {source && (
        <div className="mt-1 text-xs text-gray-500">
          Suggested by {I0_SOURCE_LABEL[source] ?? source}
        </div>
      )}
      {typeof error === 'string' && (
        <p className="mt-1 text-xs text-red-600">{error}</p>
      )}
    </div>
  )
}


function BandPair({
  label,
  minName,
  maxName,
  form,
  source,
}: {
  label: string
  minName: FormFieldName
  maxName: FormFieldName
  form: ReturnType<typeof useForm<FormValues>>
  source?: string
}) {
  const minError = form.formState.errors[minName]?.message
  const maxError = form.formState.errors[maxName]?.message
  return (
    <div className="col-span-1 sm:col-span-2">
      <div className="text-sm font-medium text-gray-700 mb-1">{label}</div>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          max={100}
          {...form.register(minName, { valueAsNumber: true })}
          aria-label={`${label} min`}
          className={cn(
            'w-24 rounded-md border border-gray-300 px-3 py-2 text-sm',
            'focus:outline-none focus:ring-2 focus:ring-offset-1',
          )}
        />
        <span className="text-sm text-gray-500">to</span>
        <input
          type="number"
          min={0}
          max={100}
          {...form.register(maxName, { valueAsNumber: true })}
          aria-label={`${label} max`}
          className={cn(
            'w-24 rounded-md border border-gray-300 px-3 py-2 text-sm',
            'focus:outline-none focus:ring-2 focus:ring-offset-1',
          )}
        />
        <span className="text-sm text-gray-500">%</span>
      </div>
      {source && (
        <div className="mt-1 text-xs text-gray-500">
          Suggested by {I0_SOURCE_LABEL[source] ?? source}
        </div>
      )}
      {typeof minError === 'string' && (
        <p className="mt-1 text-xs text-red-600">{minError}</p>
      )}
      {typeof maxError === 'string' && (
        <p className="mt-1 text-xs text-red-600">{maxError}</p>
      )}
    </div>
  )
}


function ProhibitedTagsInput({
  value,
  onChange,
}: {
  value: string[]
  onChange: (next: string[]) => void
}) {
  const [draft, setDraft] = useState('')
  const addCurrent = () => {
    const trimmed = draft.trim()
    if (!trimmed) return
    if (value.includes(trimmed)) {
      setDraft('')
      return
    }
    onChange([...value, trimmed])
    setDraft('')
  }
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {value.map((p) => (
          <span
            key={p}
            className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-700"
          >
            {p}
            <button
              type="button"
              onClick={() => onChange(value.filter((x) => x !== p))}
              className="text-gray-500 hover:text-gray-900"
              aria-label={`Remove ${p}`}
            >
              <X size={10} />
            </button>
          </span>
        ))}
        {value.length === 0 && (
          <span className="text-xs text-gray-400">No prohibitions yet</span>
        )}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addCurrent()
            }
          }}
          placeholder="e.g. tobacco stocks, fossil fuel companies"
          className={cn(
            'flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm',
            'focus:outline-none focus:ring-2 focus:ring-offset-1',
          )}
        />
        <button
          type="button"
          onClick={addCurrent}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Add
        </button>
      </div>
    </div>
  )
}


function SoftWarningsBanner({
  warnings,
}: {
  warnings: SoftWarning[]
}) {
  // The mutation completed successfully and surfaced warnings — typically
  // the page will navigate away on success, but we render this defensively
  // so warnings on a hypothetical "stay on page" path still show.
  const visible = useMemo(() => warnings.filter((w) => Boolean(w.message)), [warnings])
  if (visible.length === 0) return null
  return (
    <div className="mb-4 rounded-md border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-900">
      <div className="font-medium mb-1">Created with warnings:</div>
      <ul className="list-disc list-inside">
        {visible.map((w) => (
          <li key={w.code}>{w.message}</li>
        ))}
      </ul>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Defaults → form-values converter
// ---------------------------------------------------------------------------


function defaultsToFormValues(d: MandateDefaults): FormValues {
  return {
    equity_min_pct: d.equity_min_pct,
    equity_max_pct: d.equity_max_pct,
    debt_min_pct: d.debt_min_pct,
    debt_max_pct: d.debt_max_pct,
    cash_min_pct: d.cash_min_pct,
    cash_max_pct: d.cash_max_pct,
    alternatives_min_pct: d.alternatives_min_pct,
    alternatives_max_pct: d.alternatives_max_pct,
    single_position_max_pct: d.single_position_max_pct,
    liquidity_floor_pct: d.liquidity_floor_pct,
    sector_max_pct: d.sector_max_pct,
    prohibited_instruments: [...d.prohibited_instruments],
  }
}
