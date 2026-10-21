import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { HealthStatus, Service, ServiceCreate, ServiceType } from './types'

export type ServiceSortKey = 'name' | 'type' | 'device' | 'port' | 'status' | 'latency' | 'last_checked' | 'vendor'

export interface ServiceFilters {
  status?: HealthStatus | ''
  service_type?: ServiceType | ''
  managed?: 'true' | 'false' | ''
  q?: string
  sort?: ServiceSortKey
  order?: 'asc' | 'desc'
}

function toQueryString(filters: ServiceFilters): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export function useServices(filters: ServiceFilters = {}) {
  return useQuery({
    queryKey: ['services', filters],
    queryFn: () => api.get<Service[]>(`/services${toQueryString(filters)}`),
    refetchInterval: 5_000,
  })
}

export function useService(id: number | null) {
  return useQuery({
    queryKey: ['services', 'one', id],
    queryFn: () => api.get<Service>(`/services/${id}`),
    enabled: id !== null,
  })
}

export function useCreateService() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ServiceCreate) => api.post<Service>('/services', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['services'] })
    },
  })
}

/** Promotes a discovered (unmanaged) service to a monitored one. */
export function useSetServiceManaged() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, managed }: { id: number; managed: boolean }) =>
      api.patch<Service>(`/services/${id}`, { managed }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['services'] })
    },
  })
}

export function useUpdateService() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: number; name?: string; device_id?: number | null }) =>
      api.patch<Service>(`/services/${id}`, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['services'] }),
  })
}

export function useDeleteService() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/services/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['services'] }),
  })
}

export type BulkAction = 'delete' | 'monitor' | 'unmonitor'

export function useBulkServices() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { ids: number[]; action: BulkAction }) =>
      api.post<{ affected: number }>('/services/bulk', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['services'] }),
  })
}

export function useRescanService() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<{ updated: number; status: string | null }>(`/services/${id}/rescan`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['services'] })
    },
  })
}
