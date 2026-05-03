import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useNavigate } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import {
  type Investor,
  type InvestorCreatePayload,
  useCreateInvestor,
  useHouseholdsList,
  InvestorCreateError,
  type DuplicatePanProblem,
} from '../../api/investors'
import { cn } from '../../lib/cn'

import { InvestorProfileCard } from './components/InvestorProfileCard'

// Per chunk plan §scope_in:
// "Form UI at /app/advisor/investors/new: Three-section single-page form
//  (Identity, Household and Assignment, Investment Profile). Field-level
//  validation on blur (client-side). sessionStorage draft persistence.
//  Submit triggers validation, then POST, then enriched profile inline."

// Zod schema mirrors src/artha/api_v2/investors/schemas.py InvestorCreateRequest.
// Validation rules are kept in lock-step with the server (FR 10.7 §2.4).
const PAN_REGEX = /^[A-Z]{5}[0-9]{4}[A-Z]$/

const formSchema = z
  .object({
    name: z
      .string()
      .min(2, 'Name must be at least 2 characters')
      .max(100, 'Name must be at most 100 characters')
      .refine((v) => v.trim().includes(' '), 'Name must contain at least one space (full name)'),
    email: z.string().email('Invalid email address'),
    phone: z
      .string()
      .min(10, 'Phone must be at least 10 digits')
      .refine(
        (v) => /^\+?\d{10,15}$/.test(v.replace(/[\s\-()]/g, '')),
        'Phone must be E.164 or a 10-digit Indian number',
      ),
    pan: z
      .string()
      .transform((v) => v.trim().toUpperCase())
      .refine((v) => PAN_REGEX.test(v), 'PAN must match the 10-character format ABCDE1234F'),
    age: z
      .number({ error: 'Age is required' })
      .int('Age must be a whole number')
      .min(18, 'Age must be at least 18')
      .max(100, 'Age must be at most 100'),
    household_choice: z.enum(['existing', 'new']),
    household_id: z.string().optional(),
    household_name: z.string().optional(),
    risk_appetite: z.enum(['aggressive', 'moderate', 'conservative']),
    time_horizon: z.enum(['under_3_years', '3_to_5_years', 'over_5_years']),
  })
  .refine(
    (data) => {
      if (data.household_choice === 'existing') return Boolean(data.household_id)
      return Boolean(data.household_name && data.household_name.trim().length > 0)
    },
    { message: 'Household is required', path: ['household_name'] },
  )

type FormValues = z.infer<typeof formSchema>

const DRAFT_KEY = 'cluster-1-new-investor-draft'

export function NewInvestorPage() {
  const navigate = useNavigate()
  const householdsQuery = useHouseholdsList()
  const createMutation = useCreateInvestor()
  const [createdInvestor, setCreatedInvestor] = useState<Investor | null>(null)
  const [duplicateWarning, setDuplicateWarning] =
    useState<DuplicatePanProblem | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    mode: 'onBlur',
    defaultValues: {
      name: '',
      email: '',
      phone: '',
      pan: '',
      age: undefined as unknown as number,
      household_choice: 'new',
      household_id: '',
      household_name: '',
      risk_appetite: 'moderate',
      time_horizon: 'over_5_years',
    },
  })

  // sessionStorage draft persistence (Ideation Log §3.3).
  useEffect(() => {
    const raw = sessionStorage.getItem(DRAFT_KEY)
    if (raw) {
      try {
        form.reset(JSON.parse(raw))
      } catch {
        // ignore corrupt draft
      }
    }
  }, [form])

  useEffect(() => {
    const sub = form.watch((value) => {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(value))
    })
    return () => sub.unsubscribe()
  }, [form])

  const householdChoice = form.watch('household_choice')

  const onSubmit = async (
    values: FormValues,
    duplicate_pan_acknowledged = false,
  ) => {
    const payload: InvestorCreatePayload = {
      name: values.name,
      email: values.email,
      phone: values.phone,
      pan: values.pan,
      age: values.age,
      risk_appetite: values.risk_appetite,
      time_horizon: values.time_horizon,
      duplicate_pan_acknowledged,
    }
    if (values.household_choice === 'existing' && values.household_id) {
      payload.household_id = values.household_id
    } else if (values.household_choice === 'new' && values.household_name) {
      payload.household_name = values.household_name
    }

    try {
      const investor = await createMutation.mutateAsync(payload)
      sessionStorage.removeItem(DRAFT_KEY)
      setCreatedInvestor(investor)
      setDuplicateWarning(null)
    } catch (err) {
      if (err instanceof InvestorCreateError && err.status === 409) {
        setDuplicateWarning(err.problem as DuplicatePanProblem)
      }
    }
  }

  // ----- success state -----
  if (createdInvestor) {
    return (
      <div className="p-8 max-w-5xl">
        <div className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          Investor created and enriched.
        </div>
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-gray-900">{createdInvestor.name}</h1>
          <p className="text-sm text-gray-500 mt-1">
            PAN <span className="font-mono">{createdInvestor.pan}</span>
          </p>
        </div>
        <InvestorProfileCard investor={createdInvestor} />
        <div className="mt-6 flex gap-3">
          <button
            type="button"
            onClick={() =>
              navigate({
                to: '/investors/$investorId',
                params: { investorId: createdInvestor.investor_id },
              })
            }
            className="rounded-md px-4 py-2 text-sm font-medium text-white"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            View Investor Detail
          </button>
          <button
            type="button"
            onClick={() => {
              setCreatedInvestor(null)
              form.reset()
            }}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Add Another Investor
          </button>
          <Link
            to="/investors"
            className="rounded-md px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Continue to Investor List
          </Link>
        </div>
      </div>
    )
  }

  // ----- form state -----
  return (
    <div className="p-8 max-w-3xl">
      <Link
        to="/investors"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to investors
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">Add New Investor</h1>
      <p className="text-sm text-gray-500 mb-8">
        Fields validate on blur. Drafts auto-save to your browser session.
      </p>

      {createMutation.isPending && (
        <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          Creating investor and running enrichment…
        </div>
      )}

      {duplicateWarning && (
        <DuplicatePanDialog
          warning={duplicateWarning}
          onCancel={() => setDuplicateWarning(null)}
          onProceed={() => {
            const v = form.getValues()
            void onSubmit(v, true)
          }}
        />
      )}

      <form onSubmit={form.handleSubmit((v) => onSubmit(v, false))} className="space-y-8">
        <Section title="Identity" description="Investor's basic identification details.">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Full Name" error={form.formState.errors.name?.message}>
              <input
                {...form.register('name')}
                placeholder="Anjali Mehta"
                className={inputClass}
              />
            </Field>
            <Field label="Age" error={form.formState.errors.age?.message}>
              <input
                {...form.register('age', { valueAsNumber: true })}
                type="number"
                min={18}
                max={100}
                className={inputClass}
              />
            </Field>
            <Field label="Email" error={form.formState.errors.email?.message}>
              <input {...form.register('email')} type="email" className={inputClass} />
            </Field>
            <Field label="Phone" error={form.formState.errors.phone?.message}>
              <input
                {...form.register('phone')}
                placeholder="+91 98765 43210 or 9876543210"
                className={inputClass}
              />
            </Field>
            <Field label="PAN" error={form.formState.errors.pan?.message}>
              <input
                {...form.register('pan')}
                placeholder="ABCDE1234F"
                maxLength={10}
                className={cn(inputClass, 'font-mono uppercase')}
              />
            </Field>
          </div>
        </Section>

        <Section title="Household and Assignment" description="Group this investor and assign an advisor.">
          <div className="space-y-4">
            <div className="flex gap-6">
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  value="new"
                  {...form.register('household_choice')}
                />
                Create new household
              </label>
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  value="existing"
                  {...form.register('household_choice')}
                />
                Use existing household
              </label>
            </div>
            {householdChoice === 'new' ? (
              <Field
                label="Household Name"
                error={form.formState.errors.household_name?.message}
              >
                <input
                  {...form.register('household_name')}
                  placeholder="Mehta Household"
                  className={inputClass}
                />
              </Field>
            ) : (
              <Field
                label="Existing Household"
                error={form.formState.errors.household_id?.message}
              >
                <select {...form.register('household_id')} className={inputClass}>
                  <option value="">Select…</option>
                  {householdsQuery.data?.map((h) => (
                    <option key={h.household_id} value={h.household_id}>
                      {h.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
        </Section>

        <Section title="Investment Profile" description="Used by I0 enrichment to infer life stage and liquidity tier.">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Risk Appetite" error={form.formState.errors.risk_appetite?.message}>
              <select {...form.register('risk_appetite')} className={inputClass}>
                <option value="aggressive">Aggressive</option>
                <option value="moderate">Moderate</option>
                <option value="conservative">Conservative</option>
              </select>
            </Field>
            <Field label="Time Horizon" error={form.formState.errors.time_horizon?.message}>
              <select {...form.register('time_horizon')} className={inputClass}>
                <option value="under_3_years">Under 3 years</option>
                <option value="3_to_5_years">3 to 5 years</option>
                <option value="over_5_years">Over 5 years</option>
              </select>
            </Field>
          </div>
        </Section>

        {createMutation.error && !duplicateWarning && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {createMutation.error.message}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <Link
            to="/investors"
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
            {createMutation.isPending ? 'Creating…' : 'Create Investor'}
          </button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tiny presentational primitives (avoiding shadcn/ui init for cluster 1)
// ---------------------------------------------------------------------------

const inputClass = cn(
  'w-full rounded-md border border-gray-300 px-3 py-2 text-sm',
  'focus:outline-none focus:ring-2 focus:ring-offset-1',
)

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

function Field({
  label,
  error,
  children,
}: {
  label: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

function DuplicatePanDialog({
  warning,
  onCancel,
  onProceed,
}: {
  warning: DuplicatePanProblem
  onCancel: () => void
  onProceed: () => void
}) {
  return (
    <div className="mb-6 rounded-md border border-yellow-300 bg-yellow-50 p-4">
      <h3 className="text-sm font-semibold text-yellow-900">
        PAN already exists
      </h3>
      <p className="text-sm text-yellow-900 mt-1">
        An investor with PAN <span className="font-mono">{warning.duplicate.pan}</span>{' '}
        already exists for{' '}
        <span className="font-medium">{warning.duplicate.duplicate_of_name}</span>{' '}
        (created{' '}
        {new Date(warning.duplicate.duplicate_of_created_at).toLocaleDateString()}).
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onProceed}
          className="rounded-md border border-yellow-400 bg-yellow-100 px-3 py-1.5 text-xs font-medium text-yellow-900 hover:bg-yellow-200"
        >
          Create separate record anyway
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
