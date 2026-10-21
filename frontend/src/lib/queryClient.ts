import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'

// A 401 from any request means the session ended (or never existed): show the login page again.
function onUnauthorized(error: unknown) {
  if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(['auth', 'me'], null)
}

export const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onUnauthorized }),
  mutationCache: new MutationCache({ onError: onUnauthorized }),
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
    },
  },
})
