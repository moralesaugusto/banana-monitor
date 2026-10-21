import { describe, expect, it } from 'vitest'
import type { Agent } from '../api/aiMode'
import { workflowEdges } from './workflow'

const agent = (id: number, name: string, over: Partial<Agent>): Agent => ({
  id, name, display_name: null, role: '', system_prompt: '', base_url: '', provider: '', credential_id: null, model_override: '', temperature: 0.2,
  max_iterations: 5, enabled_tools: [], mcp_url_override: null, mcp_timeout_seconds: 0, subscribes: [], publishes: [],
  require_approval: 'none', enabled: true, allow_changes: false, ...over,
})

describe('workflowEdges', () => {
  it('connects a publisher to every agent whose subscription its topics can reach', () => {
    const edges = workflowEdges([
      agent(1, 'discoverer', { enabled_tools: ['record_service'], subscribes: ['task.discoverer', 'human.discoverer'], publishes: ['result.#'] }),
      agent(2, 'reviewer', { subscribes: ['discovery.service.found', 'human.reviewer'], publishes: ['result.#'] }),
      agent(3, 'reporter', { subscribes: ['task.reporter', 'result.discoverer'] }),
    ])
    expect(edges).toEqual([
      { from: 'discoverer', to: 'reviewer', topic: 'discovery.service.found' },
      { from: 'discoverer', to: 'reporter', topic: 'result.discoverer' },
    ])
  })

  it('connects report_open_ports to a subscriber of discovery.ports.found', () => {
    const edges = workflowEdges([
      agent(1, 'discoverer', { enabled_tools: ['report_open_ports'], publishes: ['result.#'] }),
      agent(2, 'reviewer', { subscribes: ['discovery.ports.found', 'human.reviewer'], publishes: ['result.#'] }),
    ])
    expect(edges).toEqual([{ from: 'discoverer', to: 'reviewer', topic: 'discovery.ports.found' }])
  })

  it('does not draw an edge for human-only subscriptions', () => {
    const edges = workflowEdges([
      agent(1, 'a', { publishes: ['human.#'] }),
      agent(2, 'b', { subscribes: ['human.b'] }),
    ])
    expect(edges).toEqual([])
  })
})
