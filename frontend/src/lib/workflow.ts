import type { Agent } from '../api/aiMode'
import { patternsOverlap, topicMatches } from './bus'

/** An edge for every publisher whose allowed topics reach a subscriber. The orchestrator itself publishes
 * `discovery.ports.found` whenever an agent reports open ports, and `discovery.service.found` whenever
 * an agent records a service. */
export function workflowEdges(agents: Agent[]): { from: string; to: string; topic: string }[] {
  const edges: { from: string; to: string; topic: string }[] = []
  for (const a of agents) {
    // An agent's final answer goes to result.<name>, so a wildcard that covers it means that topic.
    const own = `result.${a.name}`
    const publishes = a.publishes.map((p) => (topicMatches(p, own) ? own : p))
    if (a.enabled_tools.includes('record_service')) publishes.push('discovery.service.found')
    if (a.enabled_tools.includes('report_open_ports')) publishes.push('discovery.ports.found')
    for (const b of agents) {
      if (a.id === b.id) continue
      const sub = b.subscribes.find((s) => !s.startsWith('human.') && publishes.some((p) => patternsOverlap(p, s)))
      if (sub) edges.push({ from: a.name, to: b.name, topic: sub })
    }
  }
  return edges
}

