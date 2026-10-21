import type { Agent } from '../api/aiMode'
import { topicMatches } from './bus'

export interface RoutedTopic {
  topic: string
  /** Agents whose publish patterns allow this topic, with the pattern that did. */
  publishers: { agent: string; pattern: string }[]
  subscribers: { agent: string; pattern: string; enabled: boolean }[]
  /** Published by the app itself, not by an agent: a human or the orchestrator. */
  implicit: string | null
}

export interface RoutingProblem {
  severity: 'warn' | 'info'
  text: string
}

const isWildcard = (pattern: string) => pattern.includes('*') || pattern.includes('#')

/** Every concrete topic worth a row: the ones the app itself uses for each agent, plus any fixed topic named in
 * a subscription or publish pattern. A wildcard cannot be listed, so it shows up as a match on these. */
function candidateTopics(agents: Agent[]): string[] {
  const topics = new Set<string>(['discovery.service.found', 'discovery.ports.found'])
  for (const a of agents) {
    topics.add(`task.${a.name}`)
    topics.add(`human.${a.name}`)
    topics.add(`result.${a.name}`)
    for (const p of [...a.subscribes, ...a.publishes]) if (!isWildcard(p)) topics.add(p)
  }
  return [...topics].sort()
}

function implicitPublisher(topic: string, agents: Agent[]): string | null {
  if (topic.startsWith('task.') || topic.startsWith('human.')) return 'human'
  if (topic === 'discovery.service.found' && agents.some((a) => a.enabled_tools.includes('record_service'))) {
    return 'orchestrator (when an agent records a service)'
  }
  if (topic === 'discovery.ports.found' && agents.some((a) => a.enabled_tools.includes('report_open_ports'))) {
    return 'orchestrator (when an agent reports open ports)'
  }
  return null
}

export function buildRouting(agents: Agent[]): { topics: RoutedTopic[]; problems: RoutingProblem[] } {
  const topics: RoutedTopic[] = candidateTopics(agents).map((topic) => ({
    topic,
    publishers: agents.flatMap((a) => {
      const pattern = a.publishes.find((p) => topicMatches(p, topic))
      return pattern ? [{ agent: a.name, pattern }] : []
    }),
    subscribers: agents.flatMap((a) => {
      const pattern = a.subscribes.find((p) => topicMatches(p, topic))
      return pattern ? [{ agent: a.name, pattern, enabled: a.enabled }] : []
    }),
    implicit: implicitPublisher(topic, agents),
  }))

  const problems: RoutingProblem[] = []
  for (const t of topics) {
    const live = t.subscribers.filter((s) => s.enabled)
    const isPublished = t.publishers.length > 0 || t.implicit !== null
    if (isPublished && live.length === 0 && !t.topic.startsWith('task.') && !t.topic.startsWith('human.')) {
      problems.push({
        severity: t.topic.startsWith('result.') ? 'info' : 'warn',
        text:
          t.subscribers.length > 0
            ? `${t.topic} can be published but its only subscribers are switched off.`
            : `${t.topic} can be published but nobody subscribes to it, so it is only logged.`,
      })
    }
  }
  for (const a of agents.filter((agent) => agent.enabled)) {
    for (const pattern of a.subscribes) {
      const reached = topics.some((t) => topicMatches(pattern, t.topic) && (t.publishers.length > 0 || t.implicit !== null))
      if (!reached) {
        problems.push({
          severity: 'warn',
          text: `${a.name} subscribes to ${pattern}, but no agent is allowed to publish a topic that matches it.`,
        })
      }
    }
  }
  return { topics, problems }
}
