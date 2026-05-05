import { Link } from '@tanstack/react-router'
import {
  Activity,
  Camera,
  Database,
  FileText,
  Gauge,
  Globe,
  Layers,
  TrendingUp,
} from 'lucide-react'

// Cluster 3 chunk 3.4 — audit-role admin landing.
//
// The audit role's home page surfaces the full D0 administrative reach:
// adapter health, staging records, every canonical-entity browser,
// snapshot machinery, and freshness monitoring. CIO + compliance can
// read these pages too (D0_ADMIN_READ); only audit can trigger adapter
// runs and create + verify snapshots (D0_ADMIN_WRITE).

interface Tile {
  to: string
  label: string
  blurb: string
  icon: typeof Activity
}

const TILES: Tile[] = [
  {
    to: '/audit/freshness',
    label: 'Data Freshness',
    blurb:
      "Monitor canonical-entity tables against their freshness SLAs. Stale tables are highlighted; very-stale tables flagged with the freshness_threshold_exceeded T1 event.",
    icon: Gauge,
  },
  {
    to: '/audit/adapters',
    label: 'Adapters',
    blurb:
      'Registered D0 adapters with health status. Trigger runs in full or validation mode.',
    icon: Activity,
  },
  {
    to: '/audit/staging',
    label: 'Staging Records',
    blurb:
      'Raw fetches preserved with content-hashes for audit replay.',
    icon: Layers,
  },
  {
    to: '/audit/snapshots',
    label: 'Snapshots',
    blurb:
      "Point-in-time captures of every canonical entity. Verify against the stored hash; diff between snapshots.",
    icon: Camera,
  },
  {
    to: '/audit/instruments',
    label: 'Instruments',
    blurb:
      'Investable instruments with SEBI category, asset class, vehicle type, and source lineage.',
    icon: Database,
  },
  {
    to: '/audit/macro-snapshots',
    label: 'Macro Snapshots',
    blurb:
      'India macro indicators by period — GDP, inflation, repo, 10y yield, FX.',
    icon: TrendingUp,
  },
  {
    to: '/audit/industry-reports',
    label: 'Industry Reports',
    blurb:
      'Sector outlook + key themes + drivers + risks per period.',
    icon: FileText,
  },
  {
    to: '/audit/sebi-categories',
    label: 'SEBI Categories',
    blurb:
      'The 46-category SEBI mutual-fund taxonomy with asset-class + vehicle-type mapping.',
    icon: Globe,
  },
]

export function AdminLandingPage() {
  return (
    <div className="p-8 max-w-6xl">
      <h1 className="text-2xl font-semibold text-gray-900 mb-2">
        Audit Console
      </h1>
      <p className="text-sm text-gray-600 mb-6 max-w-2xl">
        D0 data-foundation administration. The full canonical-entity
        surface plus adapter operations, staging records, and the snapshot
        machinery for audit replay.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {TILES.map((t) => (
          <Link
            key={t.to}
            to={t.to}
            className="block rounded-lg border border-gray-200 bg-white p-5 shadow-sm transition hover:shadow-md hover:border-gray-300"
          >
            <div className="flex items-center gap-2 mb-2 text-gray-900 font-semibold">
              <t.icon size={18} className="text-gray-500" />
              {t.label}
            </div>
            <p className="text-xs text-gray-600 leading-relaxed">{t.blurb}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}
