import { describe, expect, it } from 'vitest'
import type { AiModeSettings } from '../../api/aiMode'
import {
  agentNameError,
  applyConnectionMode,
  connectionMode,
  EMPTY,
  firstSentence,
  groupTools,
  readersOf,
  topicMatches,
} from './agentFields'
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

describe('connectionMode / applyConnectionMode', () => {
  const defaultsOllama: AiModeSettings = {
    enabled: true, system_prompt: '', model_override: '', llm_base_url: 'http://localhost:11434/v1',
    llm_model: 'qwen3:8b', llm_provider: 'ollama', llm_credential_id: null, llm_call_timeout_seconds: 60,
    max_iterations: 10, temperature: 0.2, max_targets: 25, enabled_tools: [], allow_undefined_network_scan: false,
    undefined_scan_max_hosts: 64, allow_public_targets: false, cred_allow_unlisted_hosts: false, cred_no_attempt_limit: false,
    cred_trust_new_host_keys: false, cred_pool_for_updates: false, ollama_max_concurrent_calls: 2, openrouter_max_concurrent_calls: 4,
    memory_max_entries_per_agent: 50, memory_max_content_chars: 200, memory_max_inject_chars: 4000,
    knowledge_base_enabled: false, knowledge_embedding_base_url: '', knowledge_embedding_model: 'nomic-embed-text',
    knowledge_embedding_credential_id: null, cost_budget_usd: null,
  }
  const defaultsOpenRouter: AiModeSettings = { ...defaultsOllama, llm_provider: 'openrouter', llm_credential_id: 9 }

  it('reads a pinned Ollama/OpenRouter agent back as the matching mode, and anything with its own host/key/model as custom', () => {
    expect(connectionMode({ ...EMPTY, provider: 'ollama' }, defaultsOllama)).toBe('ollama_default')
    expect(connectionMode({ ...EMPTY, provider: 'openrouter' }, defaultsOllama)).toBe('openrouter_default')
    expect(connectionMode({ ...EMPTY, provider: 'openrouter', model_override: 'x/y' }, defaultsOllama)).toBe(
      'openrouter_default',
    ) // a model is expected here, it doesn't make this custom
    expect(connectionMode({ ...EMPTY, provider: 'ollama', model_override: 'llama3' }, defaultsOllama)).toBe('custom')
    expect(connectionMode({ ...EMPTY, provider: 'ollama', base_url: 'http://gpu:11434/v1' }, defaultsOllama)).toBe('custom')
    expect(connectionMode({ ...EMPTY, provider: 'openrouter', credential_id: 3 }, defaultsOllama)).toBe('custom')
  })

  it('reads a legacy blank-provider agent as whichever mode currently matches the agents\' default', () => {
    expect(connectionMode(EMPTY, defaultsOllama)).toBe('ollama_default')
    expect(connectionMode(EMPTY, defaultsOpenRouter)).toBe('openrouter_default')
    expect(connectionMode(EMPTY, undefined)).toBe('custom') // nothing to resolve blank against yet
  })

  it('applyConnectionMode sets and clears exactly the fields each choice means', () => {
    const dirty = { ...EMPTY, provider: 'openrouter' as const, base_url: 'http://x', model_override: 'm', credential_id: 5 }
    expect(applyConnectionMode('ollama_default', dirty, defaultsOllama)).toMatchObject({
      provider: 'ollama', base_url: '', model_override: '', credential_id: null,
    })
    expect(applyConnectionMode('openrouter_default', dirty, defaultsOllama)).toMatchObject({
      provider: 'openrouter', base_url: '', credential_id: null, model_override: 'm', // kept: still editable in this mode
    })
    expect(applyConnectionMode('custom', { ...EMPTY, provider: '' }, defaultsOpenRouter)).toMatchObject({
      provider: 'openrouter', // picks up the current default so the Provider sub-select has a value
    })
  })
})
