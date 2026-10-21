import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type IntegrationStatus = 'ok' | 'error' | 'disabled' | 'unknown'

export interface IntegrationTypeInfo {
  type_key: string
  display_name: string
  config_schema: Record<string, unknown>
  credential_schema: Record<string, unknown> | null
}

export interface Integration {
  id: number
  integration_type: string
  name: string
  config: Record<string, unknown>
  credential_id: number | null
  enabled: boolean
  status: IntegrationStatus
  last_run_at: string | null
  last_error: string | null
}

export interface IntegrationCreate {
  integration_type: string
  name: string
  config?: Record<string, unknown>
  credential_id?: number | null
  enabled?: boolean
}

export function useIntegrationTypes() {
  return useQuery({
    queryKey: ['integration-types'],
    queryFn: () => api.get<IntegrationTypeInfo[]>('/integrations/types'),
  })
}

export function useIntegrations() {
  return useQuery({
    queryKey: ['integrations'],
    queryFn: () => api.get<Integration[]>('/integrations'),
  })
}

export function useCreateIntegration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: IntegrationCreate) => api.post<Integration>('/integrations', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}

/** Toggles enabled on/off - pauses a wallet entry (or any integration) without deleting it. */
export function useSetIntegrationEnabled() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.patch<Integration>(`/integrations/${id}`, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['integrations'] }),
  })
}

/** Clears the SSH host key pinned for a Generic (SSH) integration; the next poll pins whatever the host presents. */
export function useForgetHostKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<Integration>(`/integrations/${id}/forget-host-key`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['integrations'] }),
  })
}

export function useDeleteIntegration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/integrations/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}
