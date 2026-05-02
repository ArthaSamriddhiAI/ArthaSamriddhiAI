import { QueryClient } from '@tanstack/react-query'

// Conservative defaults for cluster 0:
// - retry once on transient errors (the auth refresh handles 401 itself
//   in apiFetch; this retry covers network blips).
// - no refetch-on-window-focus to avoid surprising the advisor with
//   requests when they tab back; future clusters can opt in per-query.
// - 30s stale time so static data (firm-info) doesn't refetch
//   aggressively.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})
