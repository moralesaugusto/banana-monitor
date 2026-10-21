import { describe, expect, it } from 'vitest'
import type { BusMessage } from '../api/aiMode'
import { groupConversations } from './busFlow'

const msg = (id: number, correlation_id: string, over: Partial<BusMessage> = {}): BusMessage => ({
  id, run_id: 1, ts: `2026-10-14T10:00:0${id}Z`, topic: 'result.a', sender: 'a', payload: { text: 'x' }, correlation_id,
  reply_to: null, hops: 0, status: 'delivered', note: null, deliveries: [], ...over,
})

describe('groupConversations', () => {
  it('groups by correlation id, summarising participants, depth and held messages', () => {
    const [first, second] = groupConversations([
      msg(3, 'c1', { sender: 'b', hops: 2, deliveries: [{ recipient: 'c', state: 'acked' }] }),
      msg(1, 'c1', { sender: 'human', topic: 'task.a', deliveries: [{ recipient: 'a', state: 'acked' }] }),
      msg(2, 'c2', { status: 'held' }),
      msg(4, 'c1', { topic: 'approval.tool.a', sender: 'a', status: 'held' }),
    ])
    expect(first.id).toBe('c1')
    expect(first.messages.map((m) => m.id)).toEqual([1, 3])
    expect(first.participants).toEqual(['human', 'a', 'b', 'c'])
    expect(first.maxHops).toBe(2)
    expect(first.held).toBe(0)
    expect(second.held).toBe(1)
  })

  it('returns nothing for no messages', () => {
    expect(groupConversations([])).toEqual([])
  })
})
