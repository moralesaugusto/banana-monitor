import { useEffect, useState } from 'react'
import {
  agentLabel,
  type AgentStateName,
  type AiStatus,
  useAgentControl,
  useAgents,
  useBusEvents,
  useAiStatus,
  useRunControl,
  useStartAiRun,
  useUpdateSchedule,
} from '../../api/aiMode'
import { Card } from '../../components/Card'
import { SaveBar } from '../../components/SaveBar'
import { formatDuration } from '../../lib/format'

const inputClasses = 'mt-1 w-full rounded-control border border-line bg-surface px-2 py-1 text-sm'
const buttonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50'

const STATE_STYLE: Record<AgentStateName, { label: string; dot: string; text: string; hint: string }> = {
  working: { label: 'Working', dot: 'bg-emerald-500 animate-pulse', text: 'text-emerald-600', hint: 'Handling a message right now.' },
  waiting: { label: 'Waiting', dot: 'bg-sky-500', text: 'text-sky-600', hint: 'A run is active; this agent is waiting for a message.' },
  paused: { label: 'Paused', dot: 'bg-amber-500', text: 'text-amber-600', hint: 'A human paused the run.' },
  scheduled: { label: 'Scheduled', dot: 'bg-violet-500', text: 'text-violet-600', hint: 'Idle now; takes part in the next scheduled run.' },
  stopped: { label: 'Stopped', dot: 'bg-fg-subtle', text: 'text-fg-muted', hint: 'No run is active and none is scheduled.' },
  disabled: { label: 'Disabled', dot: 'bg-fg-subtle/50', text: 'text-fg-subtle', hint: 'Switched off; takes no part in runs.' },
}

export function StateBadge({ state, queued = 0 }: { state: AgentStateName; queued?: number }) {
  const s = STATE_STYLE[state]
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${s.text}`} title={s.hint}>
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
      {queued > 0 && <span className="text-fg-muted">({queued} queued)</span>}
    </span>
  )
}

function useNow(everyMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs)
    return () => clearInterval(id)
  }, [everyMs])
  return now
}


function RunBanner({ status }: { status: AiStatus }) {
  const now = useNow()
  const control = useRunControl()
  const start = useStartAiRun()
  const { run, schedule } = status

  if (run) {
    const left = new Date(run.deadline_at).getTime() - now
    const total = new Date(run.deadline_at).getTime() - new Date(run.started_at).getTime()
    const pct = Math.min(100, Math.max(0, 100 - (left / total) * 100))
    return (
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`h-2.5 w-2.5 rounded-full ${run.paused ? 'bg-amber-500' : 'animate-pulse bg-emerald-500'}`} />
          <div className="text-sm font-medium">
            Run #{run.id} {run.paused ? 'is paused' : 'is running'}{' '}
            <span className="font-normal text-fg-muted">
              (started {run.started_by === 'schedule' ? 'by the schedule' : 'by hand'} at {new Date(run.started_at).toLocaleTimeString()})
            </span>
          </div>
          <div className="ml-auto flex gap-2">
            {run.paused ? (
              <button type="button" className={buttonClasses} onClick={() => control.resume.mutate(run.id)}>Resume</button>
            ) : (
              <button type="button" className={buttonClasses} onClick={() => control.pause.mutate(run.id)}>Pause</button>
            )}
            <button type="button" className={buttonClasses} onClick={() => control.stop.mutate(run.id)}>Stop now</button>
          </div>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-fg-subtle/20" title="Time budget used">
          <div className={`h-full ${pct > 85 ? 'bg-amber-500' : 'bg-accent'}`} style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-2 text-xs text-fg-muted">
          {left > 0
            ? `Stops by itself in ${formatDuration(left)} (at ${new Date(run.deadline_at).toLocaleTimeString()}) if the agents have not finished.`
            : 'Time limit reached; stopping.'}
        </p>
      </Card>
    )
  }

  const last = status.last_run
  const next = schedule.schedule_enabled && status.ai_enabled && schedule.next_run_at ? new Date(schedule.next_run_at).getTime() : null
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`h-2.5 w-2.5 rounded-full ${next ? 'bg-violet-500' : 'bg-fg-subtle'}`} />
        <div className="text-sm font-medium">
          No run is active.{' '}
          <span className="font-normal text-fg-muted">
            {!status.ai_enabled
              ? 'AI Mode is switched off (Settings).'
              : next
                ? next <= now
                  ? 'The next scheduled run starts within a minute.'
                  : `Next scheduled run in ${formatDuration(next - now)} (at ${new Date(next).toLocaleString()}).`
                : 'The schedule is off, so agents only run when you start them.'}
          </span>
        </div>
        <button
          type="button"
          className={`${buttonClasses} ml-auto`}
          disabled={!status.ai_enabled || start.isPending}
          onClick={() => start.mutate({ targets: [], dry_run: false, entry_agent: schedule.schedule_entry_agent })}
        >
          Start now
        </button>
      </div>
      {start.isError && <p className="mt-2 text-xs text-red-600">{start.error.message}</p>}
      {last && (
        <p className="mt-2 text-xs text-fg-muted">
          Last run #{last.id}: {last.status}
          {last.stop_reason === 'time_limit' && ', stopped automatically at the time limit'}
          {last.stop_reason === 'manual' && ', stopped by hand'}
          {last.finished_at && `, finished ${new Date(last.finished_at).toLocaleString()}`}.
        </p>
      )}
    </Card>
  )
}

function ScheduleForm({ status }: { status: AiStatus }) {
  const update = useUpdateSchedule()
  const agents = useAgents().list.data ?? []
  const s = status.schedule
  const [draft, setDraft] = useState({
    schedule_enabled: s.schedule_enabled,
    schedule_interval_seconds: s.schedule_interval_seconds,
    schedule_entry_agent: s.schedule_entry_agent,
    max_run_minutes: s.max_run_minutes,
    max_targets: s.max_targets,
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft({ ...draft, [key]: value })

  return (
    <Card className="p-4">
      <form
        className="text-sm"
        onSubmit={(e) => {
          e.preventDefault()
          update.mutate(draft)
        }}
      >
      <SaveBar
        title="Continuous loop and time limits"
        description="Agents are autonomous: a run ends when every message is handled, but never later than the time limit, whether you start it or the schedule does. Scheduled runs take the next batch of devices each time, so over several runs every device is visited. A scheduled run never interrupts one that is still going. In the loop, the next run starts the pause below after the previous one finished, so runs never pile up and the model is never overloaded; the Master Discoverer sees every configured network each time. While the loop is on, an icon is shown at the top right of the screen."
        saving={update.isPending}
        saved={update.isSuccess}
        error={update.isError ? update.error.message : null}
        label="Save schedule"
      />
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex items-center gap-2 sm:col-span-2 lg:col-span-4">
          <input type="checkbox" checked={draft.schedule_enabled} onChange={(e) => set('schedule_enabled', e.target.checked)} />
          Run in an endless loop
        </label>
        <label>
          Pause between runs (seconds)
          <input type="number" min={30} max={604800} className={inputClasses} value={draft.schedule_interval_seconds}
            onChange={(e) => set('schedule_interval_seconds', Number(e.target.value))} />
        </label>
        <label>
          Time limit per run (minutes)
          <input type="number" min={1} max={240} className={inputClasses} value={draft.max_run_minutes}
            onChange={(e) => set('max_run_minutes', Number(e.target.value))} />
        </label>
        <label>
          Devices per run
          <input type="number" min={1} max={100} className={inputClasses} value={draft.max_targets}
            onChange={(e) => set('max_targets', Number(e.target.value))} />
        </label>
        <label>
          First agent
          <select className={inputClasses} value={draft.schedule_entry_agent} onChange={(e) => set('schedule_entry_agent', e.target.value)}>
            {agents.map((a) => <option key={a.id} value={a.name}>{agentLabel(a)}</option>)}
          </select>
        </label>
      </div>
      </form>
    </Card>
  )
}

/** The run banner (working / scheduled / stopped). Live agent states are shown on the agents themselves. */
export function RunStatusPanel() {
  useBusEvents()
  const { data: status } = useAiStatus()
  if (!status) return null
  return (
    <div className="mt-6">
      <RunBanner status={status} />
    </div>
  )
}

/** Schedule and time limits for runs. */
export function SchedulePanel() {
  const { data: status } = useAiStatus()
  if (!status) return null
  return (
    <div className="mt-6">
      <ScheduleForm status={status} />
    </div>
  )
}

/** One button inside an agent's card: Stop while it is part of a running run, Start otherwise. */
export function AgentRunButton({
  agent,
  state,
  runActive,
  aiEnabled,
  control,
  targets = [],
  message = null,
}: {
  agent: { id: number; name: string; enabled: boolean }
  state: AgentStateName | undefined
  runActive: boolean
  aiEnabled: boolean
  control: ReturnType<typeof useAgentControl>
  targets?: string[]
  message?: string | null
}) {
  const buttonClasses =
    'rounded-control border px-3 py-1.5 text-sm font-medium disabled:opacity-50'
  const running = state === 'working' || state === 'waiting' || state === 'paused'
  const pending = control.start.isPending || control.stop.isPending
  const error = control.start.error ?? control.stop.error

  let action: React.ReactNode
  if (!agent.enabled) {
    action = <button type="button" disabled className={`${buttonClasses} border-line text-fg-muted`}>Disabled</button>
  } else if (running) {
    action = (
      <button type="button" disabled={pending} className={`${buttonClasses} border-red-500/50 text-red-600 hover:bg-red-500/10`}
        onClick={() => control.stop.mutate(agent.id)}>
        Stop agent
      </button>
    )
  } else {
    action = (
      <button type="button" disabled={pending || (!runActive && !aiEnabled)}
        className={`${buttonClasses} border-emerald-500/50 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-400`}
        title={
          runActive
            ? 'Bring this agent back into the run in progress.'
            : aiEnabled
              ? 'Start a run with this agent first; the others join in as messages reach them.'
              : 'AI Mode is switched off (Settings).'
        }
        onClick={() => control.start.mutate({ agentId: agent.id, targets, message })}>
        {runActive ? 'Start agent' : 'Start'}
      </button>
    )
  }
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      {action}
      {!agent.enabled || running || runActive || aiEnabled ? null : (
        <span className="text-xs text-fg-muted">AI Mode is switched off. Enable it under AI Mode settings to start agents.</span>
      )}
      {error && <span className="text-xs text-red-600 dark:text-red-400">{error.message}</span>}
    </div>
  )
}
