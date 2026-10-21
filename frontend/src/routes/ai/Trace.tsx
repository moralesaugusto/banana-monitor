import { useState } from 'react'
import type { AiRunDetail, AiRunStep } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { stuckStreaks } from './traceAnalysis'

interface ToolCallDecision {
  name: string
  arguments: unknown
}

interface LlmResponse {
  content: string | null
  reasoning: string | null
  tool_calls: ToolCallDecision[]
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function parseArgs(args: unknown): Record<string, unknown> {
  if (typeof args === 'string') {
    try {
      return asObject(JSON.parse(args))
    } catch {
      return {}
    }
  }
  return asObject(args)
}

/** One plain-English sentence per step: this is the "teach what the agent is doing" layer. */
export function explainStep(step: AiRunStep): string {
  const who = step.agent ? `[${step.agent}] ` : ''
  return who + explainStepBody(step)
}

function explainStepBody(step: AiRunStep): string {
  if (step.kind === 'error') return `The run failed: ${String(asObject(step.response).error ?? 'unknown error')}`
  if (step.kind === 'llm') {
    const response = asObject(step.response) as unknown as LlmResponse
    const calls = response.tool_calls ?? []
    if (calls.length === 0) return 'The model decided it was done and wrote its final summary.'
    const names = calls.map((c) => c.name).join(', ')
    return `The model read everything so far and decided to use ${calls.length === 1 ? 'a tool' : 'tools'}: ${names}.`
  }
  const args = asObject(step.request)
  const result = asObject(step.response)
  if (result.error) return `Tool ${step.name} was refused or failed: ${String(result.error)}`
  if (step.name === 'run_nmap') {
    return `Ran nmap on ${String(args.target)}${args.ports ? ` (ports ${String(args.ports)})` : ''} with flags ${JSON.stringify(args.flags ?? [])}.`
  }
  if (step.name === 'run_nc') return `Opened a raw connection to ${String(args.target)}:${String(args.port)} to read its banner.`
  if (step.name === 'record_service') {
    if (result.dry_run) return `Dry run: would have recorded ${String(args.ip)}:${String(args.port)} as ${String(args.service_type)}.`
    return `Recorded ${String(args.ip)}:${String(args.port)} as ${String(args.service_type)} in the Services table.`
  }
  if (step.name === 'report_open_ports') {
    const ports = Array.isArray(args.ports) ? args.ports.join(', ') : String(args.ports)
    if (result.dry_run) return `Dry run: would have reported ${String(args.ip)}'s open ports (${ports}).`
    return `Reported ${String(args.ip)}'s open ports (${ports}) for another agent to identify.`
  }
  return `Ran tool ${step.name}.`
}

export function Json({ value }: { value: unknown }) {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-control bg-fg-subtle/10 p-2 font-mono text-xs text-fg">
      {text}
    </pre>
  )
}

function Disclosure({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2">
      <button type="button" className="text-xs font-medium text-accent-strong hover:underline" onClick={() => setOpen(!open)}>
        {open ? 'Hide' : 'Show'} {label}
      </button>
      {open && <div className="mt-1">{children}</div>}
    </div>
  )
}

function StepCard({ step, stuckStreak }: { step: AiRunStep; stuckStreak?: number }) {
  const tone =
    step.kind === 'llm' ? 'border-l-sky-500' : step.kind === 'tool' ? 'border-l-emerald-500' : 'border-l-red-500'
  const label = step.kind === 'llm' ? 'Model' : step.kind === 'tool' ? 'Tool' : 'Error'
  const response = asObject(step.response)
  return (
    <Card className={`border-l-4 p-3 ${tone}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm font-medium text-fg">
          {step.idx + 1}. {label}
          {step.name && <span className="ml-2 font-mono text-xs text-fg-muted">{step.name}</span>}
        </div>
        <div className="font-mono text-xs text-fg-muted">
          {step.duration_ms} ms
          {step.kind === 'llm' && ` - ${step.prompt_tokens} in / ${step.completion_tokens} out tokens`}
        </div>
      </div>
      {stuckStreak != null && (
        <p
          className="mt-1 text-xs font-medium text-amber-600"
          title={`${step.agent ?? 'this agent'} has now failed ${step.name} the same way ${stuckStreak} times in a row - likely stuck repeating a dead end, not just slow.`}
        >
          ⚠ {stuckStreak} failed {step.name} calls in a row - may be stuck
        </p>
      )}
      <p className="mt-1 text-sm text-fg">{explainStep(step)}</p>

      {step.kind === 'llm' && (
        <>
          {typeof response.reasoning === 'string' && response.reasoning && (
            <Disclosure label="model reasoning">
              <Json value={response.reasoning} />
            </Disclosure>
          )}
          {typeof response.content === 'string' && response.content && (
            <div className="mt-2 whitespace-pre-wrap rounded-control bg-fg-subtle/10 p-2 text-sm">{response.content}</div>
          )}
          {Array.isArray(response.tool_calls) &&
            (response.tool_calls as ToolCallDecision[]).map((call, i) => (
              <div key={i} className="mt-2 font-mono text-xs">
                <span className="text-fg-muted">requested </span>
                {call.name}({JSON.stringify(parseArgs(call.arguments))})
              </div>
            ))}
          <Disclosure label="what the model was sent">
            <Json value={step.request} />
          </Disclosure>
        </>
      )}
      {step.kind === 'tool' && (
        <>
          <div className="mt-2 font-mono text-xs text-fg-muted">arguments</div>
          <Json value={step.request} />
          <div className="mt-2 font-mono text-xs text-fg-muted">result</div>
          <Json value={step.response} />
        </>
      )}
    </Card>
  )
}

export function RunMetrics({ run }: { run: AiRunDetail }) {
  const seconds =
    run.finished_at != null ? Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000) : null
  const items: [string, string][] = [
    ['Status', run.status + (run.dry_run ? ' (dry run)' : '')],
    ['Model', run.model],
    ['Steps', String(run.step_count || run.steps.length)],
    ['Services recorded', String(run.services_recorded)],
    ['Tokens in / out', `${run.prompt_tokens} / ${run.completion_tokens}`],
    ['Duration', seconds != null ? `${seconds}s` : 'running'],
  ]
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      {items.map(([label, value]) => (
        <Card key={label} className="px-3 py-2">
          <div className="text-xs text-fg-muted">{label}</div>
          <div className="mt-0.5 truncate font-mono text-sm text-fg" title={value}>
            {value}
          </div>
        </Card>
      ))}
    </div>
  )
}

export function RunTrace({ run }: { run: AiRunDetail }) {
  const streaks = stuckStreaks(run.steps)
  return (
    <div className="flex flex-col gap-3">
      <RunMetrics run={run} />
      <Card className="p-3 text-sm">
        <div className="text-xs text-fg-muted">Targets</div>
        <div className="font-mono">{run.targets.join(', ')}</div>
        <Disclosure label="system prompt used for this run">
          <Json value={run.system_prompt} />
        </Disclosure>
        <Disclosure label="settings snapshot">
          <Json value={{ ...run.settings_snapshot, base_url: run.base_url }} />
        </Disclosure>
      </Card>
      {run.steps.map((step) => (
        <StepCard key={step.idx} step={step} stuckStreak={streaks.get(step.idx)} />
      ))}
      {run.status === 'running' && <div className="text-sm text-fg-muted">Working...</div>}
      {run.error && <div className="text-sm text-red-600">{run.error}</div>}
      {run.summary && (
        <Card className="p-3">
          <div className="text-xs text-fg-muted">Final summary written by the model</div>
          <p className="mt-1 whitespace-pre-wrap text-sm">{run.summary}</p>
        </Card>
      )}
    </div>
  )
}
