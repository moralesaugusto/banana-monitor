import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type CredentialType = 'ssh_key' | 'ssh_password' | 'api_token' | 'basic_auth'

export const CREDENTIAL_TYPES: CredentialType[] = [
  'ssh_key',
  'ssh_password',
  'api_token',
  'basic_auth',
]

export interface Credential {
  id: number
  label: string
  credential_type: CredentialType
  created_at: string
  rotated_at: string | null
  last_used_at: string | null
  in_agent_pool?: boolean
  used_by: string[]
  /** Empty means nothing currently references this credential - safe to delete. */
}

export interface CredentialCreate {
  label: string
  credential_type: CredentialType
  secret: Record<string, unknown>
  in_agent_pool?: boolean
}

export function useCredentials() {
  return useQuery({
    queryKey: ['credentials'],
    queryFn: () => api.get<Credential[]>('/credentials'),
  })
}

export function useCreateCredential() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CredentialCreate) => api.post<Credential>('/credentials', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
    },
  })
}

export interface CredentialUpdate {
  label?: string
  secret?: Record<string, unknown>
  in_agent_pool?: boolean
}

export function useUpdateCredential() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: CredentialUpdate & { id: number }) =>
      api.patch<Credential>(`/credentials/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
    },
  })
}

export function useDeleteCredential() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/credentials/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
    },
  })
}
