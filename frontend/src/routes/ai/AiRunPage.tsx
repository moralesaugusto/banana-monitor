import { useState } from 'react'
import { Link } from 'react-router-dom'
import { agentLabel, useAgents, useAiModeSettings, useAiRun, useMessages, useStartAiRun } from '../../api/aiMode'
import { PageHeader } from '../../components/PageHeader'
import { useSelectedRun } from '../../lib/useSelectedRun'
import { ApprovalCard } from './MessagesPage'
import { RunPicker } from './RunPicker'
import { RunLog } from './RunLog'
import { RunMetrics } from './Trace'

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'

export function AiRunPage() {
  const { data: settings } = useAiModeSettings()
  const { runs, run: latest, setChosen } = useSelectedRun()
  const start = useStartAiRun()
  const [targets, setTargets] = useState('')
  const [dryRun, setDryRun] = useState(false)
  const [entryAgent, setEntryAgent] = useState('discoverer')
  const [message, setMessage] = useState('')
  const agents = useAgents().list.data?.filter((a) => a.enabled) ?? []

  const { data: detail } = useAiRun(latest?.id)
  const { data: messages = [] } = useMessages(latest?.id)
  const held = messages.filter((m) => m.status === 'held')
  const running = latest?.status === 'running'

  return (
    <div>
      <PageHeader
        title="AI Mode Single"
        description="Start the agents and follow everything they do as one live log: the messages they exchange, each model call and each tool they run. Click a row for the detail."
      />

      {settings && !settings.enabled && (
        <p className="mt-4 text-sm text-fg-muted">
          AI Mode is switched off. Turn it on under <Link className="text-accent-strong hover:underline" to="/ai/config">Settings</Link>.
        </p>
      )}

      <form
        className="mt-6 flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault()
          start.mutate({
            targets: targets.split(',').map((t) => t.trim()).filter(Boolean),
            dry_run: dryRun,
            entry_agent: entryAgent,
            message: message || null,
          })
        }}
      >
        <label className="flex flex-1 flex-col text-sm">
          Targets (comma separated IPs; empty means all known devices)
          <input
            className={inputClasses}
            value={targets}
            onChange={(e) => setTargets(e.target.value)}
            placeholder="192.168.1.10, 192.168.1.20"
          />
        </label>
        <label className="flex flex-col text-sm">
          Starts with agent
          <select className={inputClasses} value={entryAgent} onChange={(e) => setEntryAgent(e.target.value)}>
            {agents.map((a) => (
              <option key={a.id} value={a.name}>{agentLabel(a)}</option>
            ))}
          </select>
        </label>
        <label className="flex min-w-48 flex-1 flex-col text-sm">
          Task for that agent (optional)
          <input className={inputClasses} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Discover and record services on the targets" />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Dry run (observe only, record nothing)
        </label>
        <button
          type="submit"
          disabled={running || start.isPending || !settings?.enabled}
          className="rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:brightness-95 disabled:opacity-50"
        >
          {running ? 'Running...' : 'Run AI discovery'}
        </button>
      </form>
      {start.isError && <p className="mt-2 text-sm text-red-600">{String((start.error as Error).message).slice(0, 200)}</p>}

      <div className="mt-6 flex flex-col gap-4">
        {!latest && <p className="text-sm text-fg-muted">No runs yet. Start one to watch the agents work.</p>}
        {latest && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <RunPicker runs={runs} run={latest} onChange={setChosen} />
              <Link className="text-sm text-accent-strong hover:underline" to="/ai/runs">
                All runs
              </Link>
            </div>
            {detail && <RunMetrics run={detail} />}
            {detail && (
              <p className="text-xs text-fg-muted">
                Started {detail.started_by === 'schedule' ? 'by the loop' : 'by hand'} with {detail.entry_agent || 'discoverer'},{' '}
                {detail.targets.length} target(s)
                {detail.stop_reason === 'time_limit' && ', stopped at the time limit'}
                {detail.stop_reason === 'manual' && ', stopped by hand'}.
              </p>
            )}
            {held.length > 0 && (
              <div>
                <h2 className="mb-2 text-sm font-semibold">Waiting for you ({held.length})</h2>
                <div className="grid gap-3 lg:grid-cols-2">{held.map((m) => <ApprovalCard key={m.id} message={m} />)}</div>
              </div>
            )}
            {detail && <RunLog run={detail} messages={messages} />}
            {detail?.error && <p className="text-sm text-red-600">{detail.error}</p>}
            {detail?.summary && (
              <div className="rounded-card border border-line bg-surface p-3">
                <div className="text-xs text-fg-muted">Final summary</div>
                <p className="mt-1 whitespace-pre-wrap text-sm">{detail.summary}</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
