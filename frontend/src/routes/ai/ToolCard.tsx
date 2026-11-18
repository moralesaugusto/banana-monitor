import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ToolAvailability, ToolInfo, ToolUsage } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { Json } from './Trace'

const STATUS_STYLE: Record<ToolAvailability['status'], string> = {
  ok: 'text-emerald-600',
  missing: 'text-red-600',
  unreachable: 'text-red-600',
  blocked: 'text-amber-600',
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

function Usage({ usage }: { usage: ToolUsage | undefined }) {
  if (!usage) return <p className="mt-1 text-sm text-fg-muted">Never called yet.</p>
  return (
    <div className="mt-1 text-sm">
      <p className="text-fg-muted">
        Called {usage.calls} time{usage.calls === 1 ? '' : 's'}; {usage.errors} refused or failed. Last in{' '}
        <Link className="text-accent-strong hover:underline" to={`/ai/runs/${usage.last_run_id}`}>
          run #{usage.last_run_id}
        </Link>
        .
      </p>
      {usage.worked_run_id != null && (
        <Disclosure label={`a call that worked (run #${usage.worked_run_id})`}>
          <div className="font-mono text-xs text-fg-muted">the model asked</div>
          <Json value={usage.worked_request} />
          <div className="mt-1 font-mono text-xs text-fg-muted">what it got back</div>
          <Json value={usage.worked_response} />
        </Disclosure>
      )}
      {usage.stopped_run_id != null && (
        <Disclosure label={`a call that was stopped (run #${usage.stopped_run_id})`}>
          <div className="font-mono text-xs text-fg-muted">the model asked</div>
          <Json value={usage.stopped_request} />
          <p className="mt-1 text-sm text-red-600">Stopped: {usage.stopped_reason}</p>
        </Disclosure>
      )}
    </div>
  )
}

export function ToolCard({
  tool,
  availability,
  usage,
  children,
}: {
  tool: ToolInfo
  availability: ToolAvailability | undefined
  usage: ToolUsage | undefined
  children?: React.ReactNode
}) {
  return (
    <Card id={tool.name} className="scroll-mt-4 p-4">
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-mono text-sm font-medium">{tool.name}</div>
        <span className="shrink-0">
          <span className={`text-xs ${tool.enabled ? 'text-emerald-600' : 'text-fg-muted'}`}>
            {tool.enabled ? 'enabled' : 'disabled'}
          </span>
          {availability && (
            <span className={`ml-2 text-xs ${STATUS_STYLE[availability.status]}`} title={availability.detail}>
              {availability.status === 'ok' ? 'available' : availability.status}
            </span>
          )}
        </span>
      </div>
      <p className="mt-2 text-sm text-fg-muted">{tool.description}</p>

      <div className="mt-3 text-xs font-medium uppercase tracking-wide text-fg-muted">Where it runs</div>
      <p className="mt-1 text-sm">
        <span className="font-medium">{tool.runs_on_label}.</span> {tool.where}
      </p>

      <div className="mt-3 text-xs font-medium uppercase tracking-wide text-fg-muted">What limits it</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
        {tool.safeguards.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>

      <div className="mt-3 text-xs font-medium uppercase tracking-wide text-fg-muted">Agents that have it</div>
      <p className="mt-1 text-sm">
        {tool.agents.length === 0 && <span className="text-fg-muted">No enabled agent.</span>}
        {tool.agents.map((a, i) => (
          <span key={a.id}>
            {i > 0 && ', '}
            <Link className="font-mono text-xs text-accent-strong hover:underline" to={`/ai/agents/${a.name}`}>
              {a.name}
            </Link>
          </span>
        ))}
      </p>

      <div className="mt-3 text-xs font-medium uppercase tracking-wide text-fg-muted">How it has been used</div>
      <Usage usage={usage} />

      {children}

      <Disclosure label="the schema the model sees">
        <Json value={tool.parameters} />
      </Disclosure>
    </Card>
  )
}
