import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { tryBootRefresh } from './api/client'
import { queryClient } from './api/queryClient'
import { router } from './routes/router'

// Root component:
// 1. Tries one POST /api/v2/auth/refresh on mount so page refresh keeps
//    the user signed in (chunk 0.1 acceptance criterion 13).
// 2. Renders the QueryClientProvider so every page can use TanStack Query.
// 3. Renders the RouterProvider so TanStack Router takes over routing.

function App() {
  const [bootDone, setBootDone] = useState(false)

  useEffect(() => {
    let cancelled = false
    void tryBootRefresh().finally(() => {
      if (!cancelled) {
        setBootDone(true)
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!bootDone) {
    // Brief blocking state — keeps the dashboard's beforeLoad gate from
    // firing before we've had a chance to recover the session from the
    // refresh cookie.
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 text-sm text-gray-500">
        Loading…
      </div>
    )
  }

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

export default App
