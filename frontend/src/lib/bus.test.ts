import { describe, expect, it } from 'vitest'
import type { BusMessage } from '../api/aiMode'
import { explainMessage, patternsOverlap, topicMatches } from './bus'

describe('topicMatches', () => {
  it.each([
    ['task.discoverer', 'task.discoverer', true],
    ['task.*', 'task.reviewer', true],
    ['task.*', 'task.a.b', false],
    ['result.#', 'result', true],
    ['result.#', 'result.a.b', true],
    ['discovery.*.found', 'discovery.service.lost', false],
  ])('%s vs %s', (pattern, topic, expected) => {
    expect(topicMatches(pattern, topic)).toBe(expected)
  })
})

describe('explainMessage', () => {
  const base: BusMessage = {
    id: 1, run_id: 1, ts: '', topic: 'discovery.service.found', sender: 'discoverer', payload: { text: 'x' },
    correlation_id: 'c', reply_to: null, hops: 1, status: 'delivered', note: null,
    deliveries: [{ recipient: 'reviewer', state: 'acked' }],
  }
  it('says who received it and why', () => {
    expect(explainMessage(base)).toContain('delivered it to reviewer')
  })
  it('says when nobody listens', () => {
    expect(explainMessage({ ...base, deliveries: [] })).toContain('only logged')
  })
  it('explains a held message', () => {
    expect(explainMessage({ ...base, status: 'held' })).toContain('held')
  })
})

describe('patternsOverlap', () => {
  it.each([
    ['result.#', 'result.bellaco', true],
    ['result.#', 'task.bellaco', false],
    ['task.*', 'task.reviewer', true],
    ['task.*', 'task.a.b', false],
    ['a.b', 'a.b', true],
    ['a.b', 'a.c', false],
    ['a.#', 'a.#', true],
  ])('%s vs %s', (published, subscribed, expected) => {
    expect(patternsOverlap(published, subscribed)).toBe(expected)
  })
})
