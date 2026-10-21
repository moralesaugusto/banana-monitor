import { describe, expect, it } from 'vitest'
import { agentNameError, firstSentence, groupTools, readersOf, topicMatches } from './agentFields'
import { agent } from './fixtures'

describe('topicMatches (mirrors backend/app/llm/bus.py)', () => {
  it.each([
    ['result.#', 'result.bellaco', true],
    ['result.#', 'result', true],
    ['result.bellaco', 'result.bellaco', true],
    ['result.*', 'result.bellaco', true],
    ['result.*', 'result.bellaco.x', false],
    ['result.bellaco', 'result.maestro', false],
    ['task.bellaco', 'task', false],
    ['#', 'anything.at.all', true],
  ])('%s vs %s', (pattern, topic, expected) => {
    expect(topicMatches(pattern, topic)).toBe(expected)
  })
})

describe('readersOf', () => {
  it('lists enabled agents whose subscriptions match, excluding the agent itself', () => {
    const bellaco = agent(1, 'bellaco', { subscribes: ['result.#'] })
    const reporter = agent(2, 'reporter', { subscribes: ['result.bellaco'] })
    const off = agent(3, 'off', { subscribes: ['result.#'], enabled: false })
    expect(readersOf(bellaco, [bellaco, reporter, off])).toEqual(['reporter'])
  })
})

describe('firstSentence', () => {
  it('stops at the first full stop but not at e.g.', () => {
    expect(firstSentence('Run ONE command (os_kind linux), e.g. uname. More text.')).toBe(
      'Run ONE command (os_kind linux), e.g. uname.',
    )
    expect(firstSentence('No full stop')).toBe('No full stop')
    expect(firstSentence('')).toBe('')
  })
})

describe('groupTools', () => {
  it('groups known tools by purpose and puts the rest under custom tools', () => {
    const groups = groupTools(['run_nmap', 'ssh_readonly', 'web_search', 'whatweb', 'publish_message'])
    expect(groups.map((g) => [g.id, g.tools])).toEqual([
      ['discovery', ['run_nmap']],
      ['inspection', ['ssh_readonly']],
      ['team', ['publish_message']],
      ['internet', ['web_search']],
      ['custom', ['whatweb']],
    ])
  })
})

describe('agentNameError', () => {
  it('accepts a valid name and explains an invalid one', () => {
    expect(agentNameError('reviewer')).toBeNull()
    expect(agentNameError('QA Agent')).toMatch(/lowercase letters/)
    expect(agentNameError('')).toMatch(/2 to 30 characters/)
  })
})
