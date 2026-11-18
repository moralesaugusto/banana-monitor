import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface KnowledgeCollection {
  id: number
  name: string
  description: string
  entry_count: number
  point_count: number
  total_chars: number
}

export interface KnowledgeEntrySummary {
  id: number
  title: string
  content_excerpt: string
  source: string
  created_at: string
  updated_at: string
}

export interface KnowledgeEntry {
  id: number
  collection_id: number
  title: string
  content: string
  source: string
  embedding_model: string
  dims: number
  created_at: string
  updated_at: string
}

export interface ProjectionPoint {
  entry_id: number
  title: string
  collection_id: number
  collection_name: string
  x: number
  y: number
}

export function useKnowledgeCollections() {
  return useQuery({
    queryKey: ['knowledge', 'collections'],
    queryFn: () => api.get<KnowledgeCollection[]>('/knowledge/collections'),
  })
}

export function useCreateCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { name: string; description?: string }) =>
      api.post<KnowledgeCollection>('/knowledge/collections', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge', 'collections'] }),
  })
}

export function useReembedCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<KnowledgeCollection>(`/knowledge/collections/${id}/reembed`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useDeleteCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/knowledge/collections/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useKnowledgeEntries(collectionId: number | null) {
  return useQuery({
    queryKey: ['knowledge', 'collections', collectionId, 'entries'],
    queryFn: () => api.get<KnowledgeEntrySummary[]>(`/knowledge/collections/${collectionId}/entries`),
    enabled: collectionId !== null,
  })
}

export function useKnowledgeEntry(id: number | null) {
  return useQuery({
    queryKey: ['knowledge', 'entries', id],
    queryFn: () => api.get<KnowledgeEntry>(`/knowledge/entries/${id}`),
    enabled: id !== null,
  })
}

export function useAddEntry(collectionId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { title: string; content: string }) =>
      api.post<KnowledgeEntry[]>(`/knowledge/collections/${collectionId}/entries`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'collections', collectionId, 'entries'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'collections'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'projection'] })
    },
  })
}

export function useEditEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title, content }: { id: number; title: string; content: string }) =>
      api.put<KnowledgeEntry>(`/knowledge/entries/${id}`, { title, content }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useDeleteEntry(collectionId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/knowledge/entries/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'collections', collectionId, 'entries'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'collections'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'projection'] })
    },
  })
}

export function useDeleteAllEntries(collectionId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete<void>(`/knowledge/collections/${collectionId}/entries`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'collections', collectionId, 'entries'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'collections'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'projection'] })
    },
  })
}

export function useResetKnowledgeBase() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/knowledge/reset'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useKnowledgeProjection(collectionId?: number | null) {
  return useQuery({
    queryKey: ['knowledge', 'projection', collectionId ?? null],
    queryFn: () =>
      api.get<ProjectionPoint[]>(
        collectionId ? `/knowledge/projection?collection_id=${collectionId}` : '/knowledge/projection',
      ),
  })
}
