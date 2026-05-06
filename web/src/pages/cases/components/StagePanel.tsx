import type { ReactNode } from 'react'

interface Props {
  title: string
  subtitle?: string
  badge?: ReactNode
  children: ReactNode
}

// Generic collapsible-ish panel used by every stage row in the case
// detail view. Default open; consumers can wrap in their own
// disclosure if they need collapsibility later.

export function StagePanel({ title, subtitle, badge, children }: Props) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
          {subtitle && (
            <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>
          )}
        </div>
        {badge && <div>{badge}</div>}
      </header>
      <div className="px-5 py-4 text-sm text-gray-700">{children}</div>
    </section>
  )
}

export function KeyValue({
  label,
  value,
}: {
  label: string
  value: ReactNode
}) {
  return (
    <div className="flex justify-between gap-4 py-1">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900">{value}</span>
    </div>
  )
}

export function MutedNarrative({ text }: { text: string | null | undefined }) {
  if (!text) return <p className="italic text-gray-400">No narrative available.</p>
  return <p className="leading-relaxed text-gray-700">{text}</p>
}

// Pretty-print a JSON-ish blob for the stub/stage display. Stops short
// of full JSON syntax highlighting; the goal is readable QA, not
// developer console.
export function JsonBlock({
  value,
}: {
  value: Record<string, unknown> | null | undefined
}) {
  if (!value) return <p className="italic text-gray-400">—</p>
  return (
    <pre className="overflow-x-auto rounded bg-gray-50 p-3 text-xs text-gray-800">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}
