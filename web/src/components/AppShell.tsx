import type { ReactNode } from 'react'

import { useFirmInfo, useApplyFirmBranding } from '../firm/useFirmInfo'
import { useSSEConnection } from '../sse/useSSEConnection'

import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

// Layout wrapper for every authenticated route. Beyond layout, this is
// where two cross-cutting cluster 0 hooks are mounted exactly once per
// auth session:
//
// 1. useSSEConnection — opens the /api/v2/events/stream connection,
//    handles reconnect, demuxes the 4 cluster-0 event types, drives
//    the SSE status indicator. (FR 18.0 / chunk plan §scope_in.)
//
// 2. useFirmInfo + useApplyFirmBranding — fetches /api/v2/system/firm-info
//    and writes --color-primary / --color-accent / --logo-url to the
//    document root so Tailwind utilities (bg-primary / text-accent) and
//    the firm logo resolve correctly. (Chunk plan §scope_in /
//    Ideation Log §4.1.)
export function AppShell({ children }: { children: ReactNode }) {
  useSSEConnection()
  const firm = useFirmInfo()
  useApplyFirmBranding(firm.data)

  return (
    <div className="min-h-screen flex bg-gray-50">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  )
}
