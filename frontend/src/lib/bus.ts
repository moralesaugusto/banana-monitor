import type { BusMessage } from '../api/aiMode'

/** Topic patterns: `*` is exactly one word, `#` is everything that follows. Mirrors backend/app/llm/bus.py. */
export function topicMatches(pattern: string, topic: string): boolean {
  const p = pattern.split('.')
  const t = topic.split('.')
  for (let i = 0; i < p.length; i++) {
    if (p[i] === '#') return true
    if (i >= t.length || (p[i] !== '*' && p[i] !== t[i])) return false
  }
  return p.length === t.length
}

/** True when some topic could match both patterns, i.e. a publisher allowed `published` can reach a `subscribed` reader. */
export function patternsOverlap(published: string, subscribed: string): boolean {
  const a = published.split('.')
  const b = subscribed.split('.')
  for (let i = 0; ; i++) {
    if (a[i] === '#' || b[i] === '#') return true
    if (a[i] === undefined || b[i] === undefined) return a[i] === b[i]
    if (a[i] !== '*' && b[i] !== '*' && a[i] !== b[i]) return false
  }
}

export function messageText(message: BusMessage): string {
  const { text, ...rest } = message.payload
  if (typeof text === 'string' && Object.keys(rest).length === 0) return text
  return JSON.stringify(message.payload)
}

/** One plain-English sentence per bus message: the "teach what is happening" layer. */
export function explainMessage(m: BusMessage): string {
  const to = m.deliveries.map((d) => d.recipient)
  if (m.topic.startsWith('approval.tool.')) {
    const payload = m.payload as { tool?: string }
    const who = m.sender
    if (m.status === 'held') return `${who} wants to run ${payload.tool ?? 'a tool'} and is waiting for a human to approve it.`
    if (m.status === 'rejected') return `A human refused ${who}'s request to run ${payload.tool ?? 'a tool'}${m.note ? `: ${m.note}` : ''}.`
    return `A human approved ${who}'s request to run ${payload.tool ?? 'a tool'}.`
  }
  if (m.status === 'held') {
    return `${m.sender} published to ${m.topic} but it is held until a human approves, edits or rejects it. Nobody has received it yet.`
  }
  if (m.status === 'rejected') return `A human rejected ${m.sender}'s message to ${m.topic}${m.note ? `: ${m.note}` : ''}. No one received it.`
  const delivery =
    to.length === 0
      ? 'No agent is subscribed to that topic, so it was only logged.'
      : `The bus delivered it to ${to.join(', ')} because ${to.length === 1 ? 'its subscription matches' : 'their subscriptions match'} the topic.`
  return `${m.sender} published to ${m.topic}. ${delivery}`
}

export const NODE_HUMAN = 'human'
