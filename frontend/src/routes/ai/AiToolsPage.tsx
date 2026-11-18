import { useEffect } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { type ToolAvailability, useAiModeTools, useToolAvailability, useToolUsage } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { CustomGuardrailsEditor, CustomToolsEditor } from './CustomToolsEditor'
import { McpServersCard } from './McpServersCard'
import { PageHeader } from '../../components/PageHeader'
import { ToolCard } from './ToolCard'
import { TryCall } from './TryCall'

const STATUS_STYLE: Record<ToolAvailability['status'], string> = {
  ok: 'text-emerald-600',
  missing: 'text-red-600',
  unreachable: 'text-red-600',
  blocked: 'text-amber-600',
}

function AvailabilityCard({ items }: { items: ToolAvailability[] | undefined }) {
  const check = useToolAvailability()
  const problems = items?.filter((t) => t.status !== 'ok') ?? []
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm font-medium">Availability</div>
          <p className="mt-1 text-sm text-fg-muted">
            Looks for each tool's program on this machine and asks each MCP server what it offers. It never runs a tool.
          </p>
        </div>
        <button
          type="button"
          disabled={check.isFetching}
          onClick={() => void check.refetch()}
          className="shrink-0 rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50"
        >
          {check.isFetching ? 'Checking...' : 'Check availability'}
        </button>
      </div>
      {check.isError && <p className="mt-3 text-sm text-red-600">The check failed: {check.error.message}</p>}
      {items && (
        <div className="mt-3 text-sm">
          <div>
            {items.length - problems.length} of {items.length} tools available
          </div>
          <ul className="mt-2 space-y-1">
            {problems.map((t) => (
              <li key={t.name} className="flex gap-2">
                <span className="font-mono text-xs">{t.name}</span>
                <span className={`text-xs ${STATUS_STYLE[t.status]}`}>{t.status}</span>
                <span className="text-xs text-fg-muted">{t.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

type Tab = 'tools' | 'guardrails'

const TABS: { id: Tab; label: string }[] = [
  { id: 'tools', label: 'Tools' },
  { id: 'guardrails', label: 'Guardrails' },
]

function Tabs({ active, onChange }: { active: Tab; onChange: (tab: Tab) => void }) {
  return (
    <div role="tablist" className="mt-4 flex gap-1 border-b border-line">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={active === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
            active === t.id ? 'border-accent text-fg' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function AiToolsPage() {
  const { data } = useAiModeTools()
  const availability = useToolAvailability().data
  const byName = new Map(availability?.map((t) => [t.name, t]))
  const usage = new Map(useToolUsage().data?.map((u) => [u.name, u]))
  const { hash } = useLocation()
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'guardrails' ? 'guardrails' : 'tools'
  useEffect(() => {
    if (data && hash) document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [data, hash, tab])
  return (
    <div>
      <PageHeader
        title="Tools and guardrails"
        description="A language model cannot run anything by itself. It can only ask for one of these tools; this application decides whether to allow it, runs it, and hands the result back."
      />
      <Tabs active={tab} onChange={(t) => setParams(t === 'tools' ? {} : { tab: t })} />
      {data && tab === 'tools' && (
        <div className="mt-6 flex flex-col gap-6">
          <McpServersCard />
          <AvailabilityCard items={availability} />
          <div className="grid gap-4 lg:grid-cols-3">
            {data.tools.map((tool) => (
              <ToolCard key={tool.name} tool={tool} availability={byName.get(tool.name)} usage={usage.get(tool.name)}>
                <TryCall tool={tool} />
              </ToolCard>
            ))}
          </div>
          <CustomToolsEditor />
        </div>
      )}
      {data && tab === 'guardrails' && (
        <div className="mt-6 flex flex-col gap-6">
          <Card className="p-4">
            <div className="text-sm font-medium">Built-in guardrails (enforced in code, not editable)</div>
            <ul className="mt-2 list-disc pl-5 text-sm">
              {data.guardrails.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
            <div className="mt-3 text-xs text-fg-muted">Allowed nmap flag pattern</div>
            <pre className="mt-1 overflow-auto rounded-control bg-fg-subtle/10 p-2 font-mono text-xs">{data.allowed_nmap_flags}</pre>
          </Card>
          <CustomGuardrailsEditor />
        </div>
      )}
    </div>
  )
}
