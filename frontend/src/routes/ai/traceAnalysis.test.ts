import { describe, expect, it } from 'vitest'
import type { AiRunStep } from '../../api/aiMode'
import { stuckStreaks } from './traceAnalysis'

function step(idx: number, overrides: Partial<AiRunStep> = {}): AiRunStep {
  return {
    idx,
    ts: '2026-10-14T00:00:00Z',
    kind: 'tool',
    name: 'run_nc',
    agent: 'reviewer',
    request: {},
    response: {},
    duration_ms: 1,
    prompt_tokens: 0,
    completion_tokens: 0,
    ...overrides,
  }
}

describe('stuckStreaks', () => {
  it('flags the 3rd and later consecutive failures of the same tool by the same agent', () => {
    const steps = [
      step(0, { response: { error: 'empty' } }),
      step(1, { response: { error: 'empty' } }),
      step(2, { response: { error: 'empty' } }),
      step(3, { response: { error: 'empty' } }),
    ]
    const streaks = stuckStreaks(steps)
    expect(streaks.get(0)).toBeUndefined()
    expect(streaks.get(1)).toBeUndefined()
    expect(streaks.get(2)).toBe(3)
    expect(streaks.get(3)).toBe(4)
  })

  it('resets the streak on a success, a different tool, or a different agent', () => {
    const succeedsThenFails = [
      step(0, { response: { error: 'x' } }),
      step(1, { response: { error: 'x' } }),
      step(2, { response: {} }), // succeeds - resets
      step(3, { response: { error: 'x' } }),
      step(4, { response: { error: 'x' } }),
    ]
    expect(stuckStreaks(succeedsThenFails).size).toBe(0)

    const differentTool = [
      step(0, { response: { error: 'x' } }),
      step(1, { response: { error: 'x' } }),
      step(2, { name: 'run_nmap', response: { error: 'x' } }),
    ]
    expect(stuckStreaks(differentTool).size).toBe(0)

    const differentAgent = [
      step(0, { response: { error: 'x' } }),
      step(1, { response: { error: 'x' } }),
      step(2, { agent: 'bellaco', response: { error: 'x' } }),
    ]
    expect(stuckStreaks(differentAgent).size).toBe(0)
  })

  it('ignores llm and error steps', () => {
    const steps = [
      step(0, { kind: 'llm', response: { error: 'x' } }),
      step(1, { kind: 'error', response: { error: 'x' } }),
      step(2, { response: { error: 'x' } }),
    ]
    expect(stuckStreaks(steps).size).toBe(0)
  })
})

describe('stuckStreaks with command results', () => {
  it('counts repeated timeouts and non-zero exits reported in output', () => {
    const timeout = { exit_code: null, output: 'timed out' }
    const steps = [0, 1, 2].map((idx) => step(idx, { name: 'run_nmap', response: timeout }))
    expect(stuckStreaks(steps).get(2)).toBe(3)
    expect(stuckStreaks([...steps.slice(0, 2), step(2, { name: 'run_nmap', response: { exit_code: 0, output: '' } })]).size).toBe(0)
  })
})
