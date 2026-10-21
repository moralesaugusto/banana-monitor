import { describe, expect, it } from 'vitest'
import type { Agent } from '../api/aiMode'
import { buildRouting } from './busRouting'

const agent = (id: number, name: string, over: Partial<Agent>): Agent => ({
  id, name, display_name: null, role: '', system_prompt: '', base_url: '', provider: '', credential_id: null, model_override: '', temperature: 0.2,
  max_iterations: 5, enabled_tools: [], mcp_url_override: null, mcp_timeout_seconds: 0,
  subscribes: [`task.${name}`, `human.${name}`], publishes: [], require_approval: 'none', enabled: true,
  allow_changes: false, ...over,
})

describe('buildRouting', () => {
  const agents = [
    agent(1, 'discoverer', { enabled_tools: ['record_service'], publishes: ['result.#'] }),
    agent(2, 'reviewer', { subscribes: ['task.reviewer', 'discovery.service.found'], publishes: ['result.#'] }),
    agent(3, 'reporter', { subscribes: ['task.reporter', 'result.discoverer'] }),
  ]

  it('matches wildcard publish patterns to each agent\'s own topics and keeps the deciding pattern', () => {
    const { topics } = buildRouting(agents)
    const result = topics.find((t) => t.topic === 'result.discoverer')
    expect(result?.publishers).toEqual([
      { agent: 'discoverer', pattern: 'result.#' },
      { agent: 'reviewer', pattern: 'result.#' },
    ])
    expect(result?.subscribers).toEqual([{ agent: 'reporter', pattern: 'result.discoverer', enabled: true }])
  })

  it('credits tasks to the human and service-found to the orchestrator', () => {
    const { topics } = buildRouting(agents)
    expect(topics.find((t) => t.topic === 'task.reviewer')?.implicit).toBe('human')
    expect(topics.find((t) => t.topic === 'discovery.service.found')?.implicit).toMatch(/orchestrator/)
  })

  it('credits ports-found to the orchestrator when an agent can report open ports', () => {
    const { topics } = buildRouting([
      agent(1, 'discoverer', { enabled_tools: ['report_open_ports'], publishes: ['result.#'] }),
      agent(2, 'reviewer', { subscribes: ['task.reviewer', 'discovery.ports.found'], publishes: ['result.#'] }),
    ])
    expect(topics.find((t) => t.topic === 'discovery.ports.found')?.implicit).toMatch(/orchestrator/)
  })

  it('flags a published topic nobody reads, but only informs for a plain result topic', () => {
    const { problems } = buildRouting(agents)
    expect(problems).toContainEqual({ severity: 'info', text: expect.stringContaining('result.reviewer') })
    expect(problems.some((p) => p.severity === 'warn')).toBe(false)
  })

  it('warns when a subscription can never be reached, and when subscribers are all switched off', () => {
    const broken = [
      agent(1, 'a', { subscribes: ['task.a', 'nothing.publishes.this'] }),
      agent(2, 'b', { enabled_tools: ['record_service'], publishes: ['report.daily'] }),
      agent(3, 'c', { enabled: false, subscribes: ['task.c', 'report.daily'] }),
    ]
    const { problems } = buildRouting(broken)
    expect(problems).toContainEqual({ severity: 'warn', text: expect.stringContaining('nothing.publishes.this') })
    expect(problems).toContainEqual({ severity: 'warn', text: expect.stringContaining('only subscribers are switched off') })
  })
})
