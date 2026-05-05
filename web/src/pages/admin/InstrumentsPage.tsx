import { Link } from '@tanstack/react-router'
import { ArrowLeft, Loader2, Search } from 'lucide-react'
import { useState } from 'react'

import {
  type AssetClass,
  type VehicleType,
  useInstruments,
} from '../../api/instruments'

const ASSET_CLASSES: AssetClass[] = ['equity', 'debt', 'cash', 'alternatives']
const VEHICLE_TYPES: VehicleType[] = ['mutual_fund', 'etf', 'stock', 'bond']

export function InstrumentsPage() {
  const [search, setSearch] = useState('')
  const [assetClass, setAssetClass] = useState<AssetClass | ''>('')
  const [vehicleType, setVehicleType] = useState<VehicleType | ''>('')

  const { data, isLoading, error } = useInstruments({
    search: search || undefined,
    asset_class: assetClass || undefined,
    vehicle_type: vehicleType || undefined,
    limit: 100,
  })

  return (
    <div className="p-8 max-w-6xl">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Back to admin
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mb-2">Instruments</h1>
      <p className="text-sm text-gray-600 mb-6">
        Investable instruments: SEBI-categorised mutual funds, ETFs, listed
        equities, bonds. Filter by asset class, vehicle type, or search by
        name / ISIN / AMFI code / ticker.
      </p>

      <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm mb-4 flex flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-1 min-w-[240px]">
          <Search size={14} className="text-gray-400" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name / ISIN / AMFI / ticker"
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1"
          />
        </div>
        <select
          value={assetClass}
          onChange={(e) => setAssetClass(e.target.value as AssetClass | '')}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm"
        >
          <option value="">All asset classes</option>
          {ASSET_CLASSES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={vehicleType}
          onChange={(e) => setVehicleType(e.target.value as VehicleType | '')}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm"
        >
          <option value="">All vehicles</option>
          {VEHICLE_TYPES.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>

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
        <>
          <div className="text-xs text-gray-500 mb-2">
            {data.total} matching instrument{data.total === 1 ? '' : 's'}
          </div>
          {data.instruments.length === 0 ? (
            <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
              No instruments match these filters.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                  <tr>
                    <th className="px-4 py-2 text-left">Name</th>
                    <th className="px-4 py-2 text-left">Identifier</th>
                    <th className="px-4 py-2 text-left">Class</th>
                    <th className="px-4 py-2 text-left">Vehicle</th>
                    <th className="px-4 py-2 text-left">SEBI</th>
                    <th className="px-4 py-2 text-left">AMC</th>
                    <th className="px-4 py-2 text-left">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.instruments.map((i) => (
                    <tr key={i.instrument_id}>
                      <td className="px-4 py-2 text-gray-900">
                        {i.name}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-500">
                        {i.isin || i.amfi_scheme_code || i.exchange_ticker || '—'}
                      </td>
                      <td className="px-4 py-2 text-gray-700">
                        {i.asset_class}
                      </td>
                      <td className="px-4 py-2 text-gray-700">
                        {i.vehicle_type}
                      </td>
                      <td className="px-4 py-2 text-gray-500 text-xs">
                        {i.sebi_category || '—'}
                      </td>
                      <td className="px-4 py-2 text-gray-700 text-xs">
                        {i.amc_name || '—'}
                      </td>
                      <td className="px-4 py-2">
                        <span className="text-xs text-gray-700">
                          {i.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
