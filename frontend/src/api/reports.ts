import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface ReportSummary {
  id: number
  title: string
  source: string
  created_at: string
}

export interface Report extends ReportSummary {
  content: string
}

export function useReports() {
  return useQuery({
    queryKey: ['reports'],
    queryFn: () => api.get<ReportSummary[]>('/reports'),
    refetchInterval: 5_000,
  })
}

export function useReport(id: number | null) {
  return useQuery({
    queryKey: ['reports', id],
    queryFn: () => api.get<Report>(`/reports/${id}`),
    enabled: id !== null,
  })
}

/** Builds a report from the database right now; no model involved. */
export function useCreateSnapshotReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<Report>('/reports/snapshot'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reports'] }),
  })
}

/** Starts a run with the reporter agent; its report shows up in the list when it is saved. */
export function useGenerateAiReport() {
  return useMutation({ mutationFn: () => api.post<{ run_id: number }>('/reports/generate') })
}

export function useDeleteReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/reports/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reports'] }),
  })
}

export function useDeleteAllReports() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete<void>('/reports'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reports'] }),
  })
}

export const reportPdfUrl = (id: number) => `/api/reports/${id}/pdf`
