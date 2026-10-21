import type { BusMessage } from '../api/aiMode'

export const isRouted = (m: BusMessage) => !m.topic.startsWith('approval.')

export interface Conversation {
  id: string
  messages: BusMessage[]
  participants: string[]
  maxHops: number
  start: string
  end: string
  held: number
}

/** Messages grouped by conversation (`correlation_id`), oldest conversation first. Approval prompts are left out:
 * they are a side channel to the human, not part of the agents' conversation. */
export function groupConversations(messages: BusMessage[]): Conversation[] {
  const groups = new Map<string, BusMessage[]>()
  for (const m of messages.filter(isRouted)) groups.set(m.correlation_id, [...(groups.get(m.correlation_id) ?? []), m])
  return [...groups.entries()].map(([id, items]) => {
    const sorted = [...items].sort((a, b) => a.id - b.id)
    return {
      id,
      messages: sorted,
      participants: [...new Set(sorted.flatMap((m) => [m.sender, ...m.deliveries.map((d) => d.recipient)]))],
      maxHops: Math.max(...sorted.map((m) => m.hops)),
      start: sorted[0].ts,
      end: sorted[sorted.length - 1].ts,
      held: sorted.filter((m) => m.status === 'held').length,
    }
  })
}

export type FlowTone = 'acked' | 'delivered' | 'pending' | 'rejected' | 'dropped'

/** Colour class of one delivery arrow in the live flow, by delivery state. */
export const FLOW_STROKE: Record<FlowTone, string> = {
  acked: 'stroke-emerald-500',
  delivered: 'stroke-sky-500',
  pending: 'stroke-amber-500',
  rejected: 'stroke-red-500',
  dropped: 'stroke-fg-subtle',
}
