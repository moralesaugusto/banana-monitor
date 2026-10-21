import type { AiRunStep } from '../../api/aiMode'

const STUCK_THRESHOLD = 3

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

/** Maps a tool step's idx to how many consecutive times (>= STUCK_THRESHOLD) the same agent has now
 * failed the same tool in a row - a sign the agent is stuck repeating a dead end, as distinct from
 * ordinary model latency or a single slow call. Only set on the step where the streak first crosses the
 * threshold and every one after, so the badge stays visible for the rest of the streak. */
/** A tool step failed if it returned an `error`, or a command-style result whose `exit_code` is
 * non-zero or null (a timeout): the nmap/nc tools report those in `output`, not under `error`. */
function stepFailed(response: Record<string, unknown>): boolean {
  if (response.error) return true
  return 'exit_code' in response && response.exit_code !== 0
}

export function stuckStreaks(steps: AiRunStep[]): Map<number, number> {
  const result = new Map<number, number>()
  let streak = 0
  let key: string | null = null
  for (const step of steps) {
    if (step.kind !== 'tool') continue
    const failed = stepFailed(asObject(step.response))
    const stepKey = `${step.agent ?? ''}:${step.name ?? ''}`
    streak = failed && stepKey === key ? streak + 1 : failed ? 1 : 0
    key = failed ? stepKey : null
    if (streak >= STUCK_THRESHOLD) result.set(step.idx, streak)
  }
  return result
}
