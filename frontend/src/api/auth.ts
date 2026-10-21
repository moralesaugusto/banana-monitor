import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from './client'

export interface Me {
  username: string
  must_change_password: boolean
}

export const ME_KEY = ['auth', 'me']
const notAuth = (query: { queryKey: readonly unknown[] }) => query.queryKey[0] !== 'auth'

/** The server answers errors as {"detail": "..."}; show just the detail. */
export function errorDetail(error: Error | null): string | null {
  if (!error) return null
  try {
    const parsed = JSON.parse(error.message) as { detail?: unknown }
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {
    // not JSON: fall through
  }
  return error.message
}

/** null means signed out. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await api.get<Me>('/auth/me')
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
    staleTime: Infinity,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { username: string; password: string }) => api.post<Me>('/auth/login', payload),
    onSuccess: (me) => {
      queryClient.setQueryData(ME_KEY, me)
      queryClient.invalidateQueries({ predicate: notAuth })
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/auth/logout'),
    onSuccess: () => {
      queryClient.removeQueries({ predicate: notAuth }) // nothing from this session stays cached
      queryClient.setQueryData(ME_KEY, null)
    },
  })
}

export function useChangePassword() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { current_password: string; new_password: string }) =>
      api.post<Me>('/auth/password', payload),
    onSuccess: (me) => queryClient.setQueryData(ME_KEY, me),
  })
}
