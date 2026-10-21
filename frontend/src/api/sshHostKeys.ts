import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface SshHostKey {
  id: number
  host: string
  port: number
  fingerprint: string
  approved: boolean
  changed: boolean
  first_seen_at: string
}

const KEY = ['ssh-host-keys']

export function useSshHostKeys() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api.get<SshHostKey[]>('/ssh-host-keys'),
    refetchInterval: 10_000,
  })
}

export function useApproveSshHostKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<SshHostKey>(`/ssh-host-keys/${id}/approve`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}

export function useForgetSshHostKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/ssh-host-keys/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}
