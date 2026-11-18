import { useState } from 'react'
import { type PipelineStage, type ToolInfo, useAgents, useTryToolCall } from '../../api/aiMode'

const MARK: Record<PipelineStage['status'], { label: string; style: string }> = {
  pass: { label: 'Passed', style: 'text-emerald-600' },
  stop: { label: 'Stopped here', style: 'font-semibold text-red-600' },
  skip: { label: 'Does not apply', style: 'text-fg-subtle' },
  note: { label: 'A human is involved', style: 'text-amber-600' },
}

/** A starting point for the arguments box: one entry per required field, so the shape is visible. */
function sample(tool: ToolInfo): string {
  const schema = tool.parameters as { properties?: Record<string, { type?: string }>; required?: string[] }
  const fields: Record<string, unknown> = {}
  for (const key of schema.required ?? []) {
    const type = schema.properties?.[key]?.type
    if (key === 'target' || key === 'ip') fields[key] = '127.0.0.1'
    else if (type === 'integer' || type === 'number') fields[key] = 0
    else if (type === 'array') fields[key] = []
    else if (type === 'boolean') fields[key] = false
    else fields[key] = ''
  }
  return JSON.stringify(fields, null, 2)
}

export function TryCall({ tool }: { tool: ToolInfo }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(() => sample(tool))
  const [agentId, setAgentId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const agents = useAgents().list.data
  const trace = useTryToolCall(tool.name)

  function submit() {
    let parsed: unknown
    try {
      parsed = JSON.parse(text || '{}')
    } catch {
      setError('The arguments must be valid JSON.')
      return
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setError('The arguments must be a JSON object, like {"target": "127.0.0.1"}.')
      return
    }
    setError(null)
    trace.mutate({ arguments: parsed as Record<string, unknown>, agent_id: agentId })
  }

  return (
    <div className="mt-2">
      <button type="button" className="text-xs font-medium text-accent-strong hover:underline" onClick={() => setOpen(!open)}>
        {open ? 'Hide' : 'Try a call'}
      </button>
      {open && (
        <div className="mt-2 rounded-control border border-line p-3">
          <p className="text-xs text-fg-muted">
            Write a call the way a model would, and see which step would stop it. Nothing is run: this only checks.
          </p>
          <label className="mt-2 block text-xs text-fg-muted">
            As agent
            <select
              className="mt-1 w-full rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg"
              value={agentId ?? ''}
              onChange={(e) => setAgentId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">No agent (skip the agent checks)</option>
              {agents?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-2 block text-xs text-fg-muted">
            Arguments (JSON)
            <textarea
              className="mt-1 h-24 w-full rounded-control border border-line bg-surface p-2 font-mono text-xs text-fg"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={trace.isPending}
            onClick={submit}
            className="mt-2 rounded-control border border-line bg-surface px-3 py-1 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50"
          >
            {trace.isPending ? 'Checking...' : 'Check this call'}
          </button>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          {trace.isError && <p className="mt-2 text-sm text-red-600">The check failed: {trace.error.message}</p>}
          {trace.data && (
            <>
              <ol className="mt-3 flex flex-col gap-2">
                {trace.data.stages.map((stage, i) => (
                  <li key={stage.id} className="flex gap-3 text-sm">
                    <span className="w-5 shrink-0 text-right font-mono text-fg-muted">{i + 1}</span>
                    <span className="flex-1">
                      <span className="text-fg">{stage.title}</span>{' '}
                      <span className={`text-xs ${MARK[stage.status].style}`}>{MARK[stage.status].label}</span>
                      <span className="block text-xs text-fg-muted">{stage.detail}</span>
                    </span>
                  </li>
                ))}
              </ol>
              {trace.data.command && (
                <pre className="mt-2 overflow-auto rounded-control bg-fg-subtle/10 p-2 font-mono text-xs">{trace.data.command}</pre>
              )}
              <p className={`mt-2 text-sm font-medium ${trace.data.would_run ? 'text-emerald-600' : 'text-red-600'}`}>
                {trace.data.would_run ? 'This call would go through.' : 'This call would be stopped.'}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
