import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Device, DeviceCreate, DeviceDetail, DeviceListItem, MetricPoint } from './types'

export function useDevices() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: () => api.get<DeviceListItem[]>('/devices'),
    refetchInterval: 5_000,
  })
}

export function useDevice(id: number) {
  return useQuery({
    queryKey: ['devices', id],
    queryFn: () => api.get<DeviceDetail>(`/devices/${id}`),
    refetchInterval: 5_000,
  })
}

export function useDeviceMetricHistory(id: number, metricName: string, enabled: boolean) {
  return useQuery({
    queryKey: ['devices', id, 'metrics', metricName],
    queryFn: () => api.get<MetricPoint[]>(`/devices/${id}/metrics/${metricName}`),
    refetchInterval: 5_000,
    enabled,
  })
}

export function useCreateDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: DeviceCreate) => api.post<Device>('/devices', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    },
  })
}

export function useDeleteDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/devices/${id}`),
    onSuccess: (_, id) => {
      // Skip the deleted device's own detail query: its page is still mounted for a moment and would
      // refetch a device that is gone.
      queryClient.invalidateQueries({ queryKey: ['devices'], predicate: (q) => q.queryKey[1] !== id })
    },
  })
}

/** Re-detects open ports and fingerprints them with nmap; resolves when done. */
export function useRescanDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<{ updated: number }>(`/devices/${id}/rescan`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      queryClient.invalidateQueries({ queryKey: ['services'] })
    },
  })
}
