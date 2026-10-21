import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type NodeKind = 'network' | 'device' | 'service' | 'integration'

export interface TopologyNode {
  id: string
  kind: NodeKind
  label: string
  subtitle: string | null
  status: string | null
  entity_id: number
  meta: Record<string, unknown>
}

export interface TopologyEdge {
  source: string
  target: string
  relation: string
}

export interface Topology {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  truncated: boolean
}

export function useTopology(networkId: number | null) {
  return useQuery({
    queryKey: ['topology', networkId],
    queryFn: () => api.get<Topology>(`/topology${networkId ? `?network_id=${networkId}` : ''}`),
    refetchInterval: 15_000,
  })
}
