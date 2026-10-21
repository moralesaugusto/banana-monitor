import '@xyflow/react/dist/style.css'
import {
  Background,
  Controls,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  useNodesState,
} from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  type Agent,
  type AgentActivity,
  type AgentStateName,
  type AiStatus,
  agentLabel,
  useAgentControl,
  useAgents,
  useAiStatus,
  useBusEvents,
  useMessages,
  useUpdateAgentWorkflow,
  useUpdateSchedule,
} from '../../api/aiMode'
import { PageHeader } from '../../components/PageHeader'
import { workflowEdges } from '../../lib/workflow'
import { RunStatusPanel, StateBadge } from './AgentStatus'

const SCHEDULE_NODE = 'schedule'
const COLUMN = 320
const ROW = 210
/** Above this many agents in one BFS layer, alternate rows get an extra half-column offset so boxes
 * don't read as one undifferentiated stack - a light layout tweak, not a real graph-layout algorithm. */
const CROWDED_LAYER = 4
/** A message counts as "flowing" on its edge for this long after delivery - long enough to see the
 * animation at the page's 3s poll interval, short enough that it reads as "just happened". */
const FLOW_WINDOW_MS = 4_000

const ACTIVITY_LABEL: Record<Exclude<AgentActivity, null>, string> = {
  llm: 'Waiting on model reply',
  tool: 'Running tool call(s)',
  held: 'Held for approval',
}

const ACTIVITY_RING: Record<Exclude<AgentActivity, null>, string> = {
  llm: 'ring-2 ring-emerald-500/60 animate-pulse',
  tool: 'ring-2 ring-sky-500/60',
  held: 'ring-2 ring-amber-500/70',
}

interface AgentNodeData extends Record<string, unknown> {
  agent: Agent
  state: AgentStateName
  activity: AgentActivity
  queued: number
  aiEnabled: boolean
}

interface ScheduleNodeData extends Record<string, unknown> {
  status: AiStatus
}

type FlowNode = Node<AgentNodeData, 'agent'> | Node<ScheduleNodeData, 'schedule'>

const buttonClasses = 'nodrag rounded-control border px-2 py-1 text-xs font-medium disabled:opacity-50'

function AgentNode({ data }: NodeProps<Node<AgentNodeData, 'agent'>>) {
  const { agent, state, activity, queued, aiEnabled } = data
  const update = useUpdateAgentWorkflow()
  const control = useAgentControl()
  const navigate = useNavigate()
  const running = state === 'working' || state === 'waiting' || state === 'paused'
  const ring = !agent.enabled ? '' : activity ? ACTIVITY_RING[activity] : ''
  return (
    <div
      className={`w-64 rounded-card border bg-surface p-3 text-fg shadow-sm ${
        agent.enabled ? 'border-line' : 'border-dashed border-line opacity-60'
      } ${ring}`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-start justify-between gap-2">
        <div
          className="nodrag min-w-0 cursor-pointer"
          role="button"
          tabIndex={0}
          title={`Edit ${agentLabel(agent)}`}
          onClick={() => navigate(`/ai/agents/${agent.name}/edit`)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') navigate(`/ai/agents/${agent.name}/edit`)
          }}
        >
          <div className="truncate text-sm font-semibold hover:underline">{agentLabel(agent)}</div>
          <div className="mt-0.5 line-clamp-2 text-xs text-fg-muted">{agent.role || 'No role set'}</div>
        </div>
        <label
          className="nodrag flex shrink-0 cursor-pointer items-center gap-1 text-xs"
          title="Inactive agents take no part in runs."
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            role="switch"
            aria-label={`${agentLabel(agent)} active`}
            checked={agent.enabled}
            disabled={update.isPending || running}
            onChange={(e) => update.mutate({ id: agent.id, enabled: e.target.checked })}
          />
          Active
        </label>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <StateBadge state={state} queued={queued} />
        {running ? (
          <button
            type="button"
            className={`${buttonClasses} border-red-500/50 text-red-600 hover:bg-red-500/10`}
            disabled={control.stop.isPending}
            onClick={(e) => {
              e.stopPropagation()
              control.stop.mutate(agent.id)
            }}
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            className={`${buttonClasses} border-emerald-500/50 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-400`}
            disabled={!agent.enabled || !aiEnabled || control.start.isPending}
            title={aiEnabled ? 'Run this agent on its own' : 'AI Mode is switched off (Settings).'}
            onClick={(e) => {
              e.stopPropagation()
              control.start.mutate({ agentId: agent.id })
            }}
          >
            Run
          </button>
        )}
      </div>
      {activity && (
        <div className="mt-1 text-[11px] text-fg-muted" data-testid="agent-activity">
          {ACTIVITY_LABEL[activity]}
        </div>
      )}
      {(control.start.isError || control.stop.isError) && (
        <p className="mt-1 text-xs text-red-600">{(control.start.error ?? control.stop.error)?.message}</p>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function ScheduleNode({ data }: NodeProps<Node<ScheduleNodeData, 'schedule'>>) {
  const { schedule } = data.status
  const update = useUpdateSchedule()
  const [invalid, setInvalid] = useState(false)
  return (
    <div className={`w-64 rounded-card border border-accent bg-surface p-3 text-fg shadow-sm ${schedule.schedule_enabled ? '' : 'opacity-70'}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">Loop trigger</div>
          <div className="mt-0.5 text-xs text-fg-muted">Starts a run, then waits and starts the next</div>
        </div>
        <label className="nodrag flex cursor-pointer items-center gap-1 text-xs">
          <input
            type="checkbox"
            role="switch"
            aria-label="Loop on"
            checked={schedule.schedule_enabled}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ schedule_enabled: e.target.checked })}
          />
          On
        </label>
      </div>
      <label className="nodrag mt-2 flex items-center gap-2 text-xs">
        Pause (s)
        <input
          type="number"
          min={30}
          max={604800}
          className="w-24 rounded-control border border-line bg-surface px-2 py-1 text-xs"
          key={schedule.schedule_interval_seconds}
          defaultValue={schedule.schedule_interval_seconds}
          aria-label="Pause between runs in seconds"
          onBlur={(e) => {
            const seconds = Number(e.target.value)
            const valid = Number.isInteger(seconds) && seconds >= 30 && seconds <= 604800
            setInvalid(!valid)
            if (valid && seconds !== schedule.schedule_interval_seconds) update.mutate({ schedule_interval_seconds: seconds })
          }}
        />
      </label>
      {invalid && <p className="mt-1 text-xs text-red-600">30 to 604800 seconds</p>}
      {update.isError && <p className="mt-1 text-xs text-red-600">{update.error.message}</p>}
      <p className="mt-2 text-xs text-fg-muted">
        {!schedule.schedule_enabled
          ? 'Off: agents only run when you start them.'
          : schedule.next_run_at
            ? `Next run at ${new Date(schedule.next_run_at).toLocaleTimeString()}`
            : 'A run is in progress.'}
      </p>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { agent: AgentNode, schedule: ScheduleNode }

function defaultPositions(agents: Agent[], entry: string, edges: { from: string; to: string }[]) {
  const layer = new Map<string, number>([[entry, 0]])
  for (let pass = 0; pass < agents.length; pass++) {
    for (const e of edges) {
      const from = layer.get(e.from)
      if (from !== undefined && !layer.has(e.to)) layer.set(e.to, from + 1)
    }
  }
  const lastLayer = Math.max(0, ...layer.values())
  const layerSize = new Map<number, number>()
  for (const a of agents) {
    const l = layer.get(a.name) ?? lastLayer + 1
    layerSize.set(l, (layerSize.get(l) ?? 0) + 1)
  }
  const rows = new Map<number, number>()
  const positions = new Map<string, { x: number; y: number }>()
  for (const a of agents) {
    const l = layer.get(a.name) ?? lastLayer + 1
    const row = rows.get(l) ?? 0
    rows.set(l, row + 1)
    const crowded = (layerSize.get(l) ?? 0) > CROWDED_LAYER
    const x = (l + 1) * COLUMN + (crowded && row % 2 === 1 ? COLUMN / 2 : 0)
    positions.set(a.name, { x, y: row * ROW })
  }
  return positions
}

function WorkflowLegend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
      <span className="font-medium text-fg">Legend:</span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded border-2 border-emerald-500/60" /> waiting on the model
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded border-2 border-sky-500/60" /> running a tool call
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded border-2 border-amber-500/70" /> held for approval
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded border-2 border-dashed border-line opacity-60" /> disabled, or the
        link is to a disabled agent
      </span>
      <span className="inline-flex items-center gap-1.5">
        <svg width="18" height="8" className="shrink-0"><line x1="0" y1="4" x2="18" y2="4" stroke="var(--color-accent)" strokeWidth="2" /></svg>
        a message is moving along this edge
      </span>
    </div>
  )
}

export function WorkflowPage() {
  useBusEvents()
  const { list } = useAgents()
  const { data: status } = useAiStatus()
  const { data: recentMessages } = useMessages(status?.run?.id)
  const update = useUpdateAgentWorkflow()
  const agents = useMemo(() => list.data ?? [], [list.data])
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([])

  const edgeSpecs = useMemo(() => workflowEdges(agents), [agents])

  useEffect(() => {
    if (!status) return
    const defaults = defaultPositions(agents, status.schedule.schedule_entry_agent, edgeSpecs)
    setNodes((previous) => {
      const old = new Map(previous.map((n) => [n.id, n.position]))
      const built: FlowNode[] = agents.map((agent) => {
        const live = status.agents.find((s) => s.name === agent.name)
        const saved = agent.workflow_x != null && agent.workflow_y != null ? { x: agent.workflow_x, y: agent.workflow_y } : null
        return {
          id: agent.name,
          type: 'agent',
          position: old.get(agent.name) ?? saved ?? defaults.get(agent.name) ?? { x: 0, y: 0 },
          data: {
            agent,
            state: live?.state ?? 'stopped',
            activity: live?.activity ?? null,
            queued: live?.queued ?? 0,
            aiEnabled: status.ai_enabled,
          },
        }
      })
      built.push({
        id: SCHEDULE_NODE,
        type: 'schedule',
        position: old.get(SCHEDULE_NODE) ?? { x: 0, y: 0 },
        data: { status },
      })
      return built
    })
  }, [agents, status, edgeSpecs, setNodes])

  const edges: Edge[] = useMemo(() => {
    const byName = new Map(agents.map((a) => [a.name, a]))
    const queued = new Map(status?.agents.map((s) => [s.name, s.queued]))
    const now = Date.now()
    const recentlyFlowing = new Set(
      (recentMessages ?? [])
        .filter((m) => now - new Date(m.ts).getTime() < FLOW_WINDOW_MS)
        .flatMap((m) => m.deliveries.map((d) => `${m.sender}>${d.recipient}`)),
    )
    const flow: Edge[] = edgeSpecs.map((e) => {
      const active = byName.get(e.from)?.enabled && byName.get(e.to)?.enabled
      const id = `${e.from}>${e.to}`
      return {
        id,
        source: e.from,
        target: e.to,
        label: e.topic,
        animated: recentlyFlowing.has(id) || (queued.get(e.to) ?? 0) > 0,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: 'var(--color-fg-muted)', strokeDasharray: active ? undefined : '4 4', opacity: active ? 1 : 0.4 },
        labelStyle: { fontSize: 10, fill: 'var(--color-fg-muted)' },
        labelBgStyle: { fill: 'var(--color-surface)' },
      }
    })
    if (status) {
      flow.push({
        id: 'loop>entry',
        source: SCHEDULE_NODE,
        target: status.schedule.schedule_entry_agent,
        markerEnd: { type: MarkerType.ArrowClosed },
        animated: status.schedule.schedule_enabled && !!status.run,
        style: { stroke: 'var(--color-accent)', opacity: status.schedule.schedule_enabled ? 1 : 0.4 },
      })
    }
    return flow
  }, [agents, edgeSpecs, status, recentMessages])

  return (
    <div>
      <PageHeader
        actions={<Link className="text-sm text-accent-strong hover:underline" to="/ai/bus">Message routing</Link>}
        title="AI Workflow"
        description="Each box is an agent. Arrows follow the topics one agent publishes and another subscribes to, so a connected agent reacts on its own when the one before it finishes. Switch an agent off to leave it out of runs, run one by itself with Run, or turn on the loop trigger to repeat the first agent with a pause between runs. Drag boxes to arrange them; positions are saved."
      />
      <RunStatusPanel />
      <WorkflowLegend />
      <div className="mt-2 h-[32rem] overflow-hidden rounded-card border border-line bg-surface" data-testid="workflow-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStop={(_, node) => {
            if (node.id === SCHEDULE_NODE) return
            const agent = agents.find((a) => a.name === node.id)
            if (agent) update.mutate({ id: agent.id, workflow_x: node.position.x, workflow_y: node.position.y })
          }}
          nodesConnectable={false}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  )
}
