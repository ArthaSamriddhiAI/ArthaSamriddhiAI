import { Link } from '@tanstack/react-router'
import { ArrowLeft, Loader2 } from 'lucide-react'

import { useSebiCategories } from '../../api/instruments'

const ASSET_CLASS_STYLES: Record<string, string> = {
  equity: 'bg-blue-100 text-blue-800',
  debt: 'bg-amber-100 text-amber-800',
  cash: 'bg-green-100 text-green-800',
  alternatives: 'bg-purple-100 text-purple-800',
}

export function SebiCategoriesPage() {
  const { data, isLoading, error } = useSebiCategories()

  return (
    <div className="p-8 max-w-4xl">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to admin
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">
        SEBI Categories
      </h1>
      <p className="text-sm text-gray-600 mb-6">
        The SEBI mutual-fund taxonomy with the asset_class +
        vehicle_type pair Samriddhi maps each category to. Liquid +
        overnight + ultra-short + arbitrage map to <em>cash</em> reflecting
        Indian wealth-management practice.
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

      {data && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-4 py-2 text-left">Category</th>
                <th className="px-4 py-2 text-left">Asset Class</th>
                <th className="px-4 py-2 text-left">Vehicle Type</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.categories.map((c) => (
                <tr key={c.category}>
                  <td className="px-4 py-2 font-mono text-gray-900">
                    {c.category}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                        ASSET_CLASS_STYLES[c.asset_class] ?? 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {c.asset_class}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-700">
                    {c.vehicle_type}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
