import { useState } from 'react'
import {
  type CustomTool,
  type CustomToolInput,
  type Guardrail,
  type GuardrailInput,
  type ToolTestResult,
  useCustomTools,
  useGuardrails,
  useTestAllCustomTools,
  useTestCustomTool,
} from '../../api/aiMode'
import { Card } from '../../components/Card'
import { SaveBar } from '../../components/SaveBar'

const inputClasses = 'mt-1 w-full rounded-control border border-line bg-surface px-2 py-1 text-sm'
const buttonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50'
const linkClasses = 'text-xs font-medium text-accent-strong hover:underline'

const EMPTY_TOOL: CustomToolInput = {
  name: '',
  description: '',
  kind: 'command',
  command: [],
  mcp_url: null,
  mcp_tool: null,
  parameters: {},
  enabled: true,
}

function ToolForm({ initial, onDone }: { initial: CustomTool | null; onDone: () => void }) {
  const { save } = useCustomTools()
  const [draft, setDraft] = useState<CustomToolInput>(initial ?? EMPTY_TOOL)
  const [commandText, setCommandText] = useState((initial?.command ?? []).join(' '))
  const [error, setError] = useState<string | null>(null)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const input: CustomToolInput = { ...draft, command: commandText.split(/\s+/).filter(Boolean) }
    save.mutate({ id: initial?.id, input }, { onSuccess: onDone, onError: (e) => setError(e.message) })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 text-sm">
      <SaveBar
        title={initial ? `Edit ${initial.name}` : 'New tool'}
        saving={save.isPending}
        error={error}
        label={initial ? 'Save tool' : 'Add tool'}
        onCancel={onDone}
      />
      <label>
        Name
        <input className={inputClasses} value={draft.name} placeholder="whatweb_scan"
          onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
      </label>
      <label>
        Description the model sees
        <input className={inputClasses} value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      </label>
      <label>
        Command (no shell; {'{target}'} and {'{port}'} are substituted)
        <input className={`${inputClasses} font-mono`} value={commandText} placeholder="whatweb --no-errors {target}"
          onChange={(e) => setCommandText(e.target.value)} />
      </label>
    </form>
  )
}

function GuardrailForm({ initial, onDone }: { initial: Guardrail | null; onDone: () => void }) {
  const { save } = useGuardrails()
  const [draft, setDraft] = useState<GuardrailInput>(
    initial ?? { name: '', description: '', kind: 'deny_regex', pattern: '', enabled: true, applies_to: 'default' },
  )
  const [error, setError] = useState<string | null>(null)
  return (
    <form
      className="flex flex-col gap-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({ id: initial?.id, input: draft }, { onSuccess: onDone, onError: (err) => setError(err.message) })
      }}
    >
      <SaveBar
        title={initial ? `Edit ${initial.name}` : 'New guardrail'}
        saving={save.isPending}
        error={error}
        label={initial ? 'Save guardrail' : 'Add guardrail'}
        onCancel={onDone}
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <label>
          Name
          <input className={inputClasses} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <label>
          Rule
          <select className={inputClasses} value={draft.kind}
            onChange={(e) => setDraft({ ...draft, kind: e.target.value as Guardrail['kind'] })}>
            <option value="deny_regex">Block values that match</option>
            <option value="allow_regex">Block values that do not match</option>
          </select>
        </label>
        <label>
          Regular expression
          <input className={`${inputClasses} font-mono`} value={draft.pattern} placeholder="^(22|3389)$"
            onChange={(e) => setDraft({ ...draft, pattern: e.target.value })} />
        </label>
      </div>
      <label>
        Applies to
        <select className={inputClasses} value={draft.applies_to}
          onChange={(e) => setDraft({ ...draft, applies_to: e.target.value as Guardrail['applies_to'] })}>
          <option value="default">Custom tools and host-inspection tools (ssh, winrm, proxmox, http)</option>
          <option value="all">Every tool, including nmap, nc, web and the rest</option>
        </select>
        <span className="mt-1 block text-xs text-fg-muted">
          The rule looks at every argument value, including list items such as nmap flags. Try a call on the Tools
          page to see whether it would stop one.
        </span>
      </label>
      <label>
        Description
        <input className={inputClasses} value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      </label>
    </form>
  )
}

/** Repoints every MCP custom tool's own address at once (tajonaso's ~150 tools included) -
 * instead of editing each tool row individually when the server moves to a new host. An
 * agent's own "MCP server override" (its edit page) still replaces this for that agent only. */
export function TestResult({ result }: { result: ToolTestResult | undefined }) {
  if (!result) return null
  return (
    <div className={`mt-1 w-full text-xs ${result.ok ? 'text-emerald-600' : 'text-red-600'}`}>
      {result.ok ? 'Called successfully' : 'Failed'} in {result.duration_ms} ms
      {!result.ok && `: ${result.detail}`}
      {Object.keys(result.arguments_used).length > 0 && (
        <span className="ml-1 font-mono text-fg-subtle">{JSON.stringify(result.arguments_used)}</span>
      )}
    </div>
  )
}

export function CustomToolsEditor() {
  const tools = useCustomTools()
  const [editing, setEditing] = useState<CustomTool | 'new' | null>(null)
  const [results, setResults] = useState<Record<number, ToolTestResult>>({})
  const testOne = useTestCustomTool()
  const testAll = useTestAllCustomTools()
  const [filter, setFilter] = useState('')
  const own = (tools.list.data ?? []).filter((t) => t.mcp_server_id == null)
  const visible = own.filter(
    (t) => !filter || `${t.name} ${t.description}`.toLowerCase().includes(filter.toLowerCase()),
  )

  function runOne(id: number) {
    testOne.mutate(id, { onSuccess: (r) => setResults((prev) => ({ ...prev, [id]: r })) })
  }
  function runAll() {
    testAll.mutate(undefined, {
      onSuccess: (rows) => setResults((prev) => ({ ...prev, ...Object.fromEntries(rows.map((r) => [r.id, r])) })),
    })
  }
  const allResults = testAll.data
  const allFailures = allResults?.filter((r) => !r.ok) ?? []

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Your tools (local commands)</div>
        {editing === null && (
          <button type="button" className={buttonClasses} onClick={() => setEditing('new')}>
            Add tool
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-fg-muted">
        Custom tools get the same target check as built-ins (one IP inside a configured network) and your
        guardrails below. Turn a tool on for an agent under Agents.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-control bg-canvas p-3">
        <button type="button" disabled={testAll.isPending} className={buttonClasses} onClick={runAll}>
          {testAll.isPending ? 'Testing all...' : 'Test all tools'}
        </button>
        <span className="text-xs text-fg-muted">
          Actually calls every enabled tool against 127.0.0.1 - not a listing check. May take a while for many
          MCP tools on one server.
        </span>
        {allResults && (
          <span className={`text-xs font-medium ${allFailures.length ? 'text-red-600' : 'text-emerald-600'}`}>
            {allFailures.length === 0
              ? `All ${allResults.length} tool(s) called successfully.`
              : `${allFailures.length} of ${allResults.length} tool(s) failed: ${allFailures.map((f) => f.name).join(', ')}.`}
          </span>
        )}
      </div>

      {editing !== null && (
        <div className="mt-3">
          <ToolForm initial={editing === 'new' ? null : editing} onDone={() => setEditing(null)} />
        </div>
      )}
      {own.length > 10 && (
        <input
          aria-label="Filter tools"
          className={`${inputClasses} mt-3 w-72`}
          placeholder="Filter tools by name or description"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      )}
      <ul className="mt-3 divide-y divide-line text-sm">
        {visible.map((tool) => (
          <li key={tool.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div className="min-w-0 flex-1">
              <span className="font-mono font-medium">{tool.name}</span>{' '}
              <span className="text-xs text-fg-muted">{tool.command.join(' ')}</span>
              <div className="text-xs text-fg-muted">{tool.description}</div>
              <TestResult result={results[tool.id]} />
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                className={linkClasses}
                disabled={testOne.isPending && testOne.variables === tool.id}
                onClick={() => runOne(tool.id)}
              >
                {testOne.isPending && testOne.variables === tool.id ? 'Testing...' : 'Test'}
              </button>
              <button type="button" className={linkClasses} onClick={() => setEditing(tool)}>Edit</button>
              <button
                type="button"
                className="text-xs font-medium text-red-600 hover:underline"
                onClick={() => window.confirm(`Delete ${tool.name}?`) && tools.remove.mutate(tool.id)}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {own.length === 0 && <li className="py-2 text-fg-muted">No custom tools yet.</li>}
      </ul>
    </Card>
  )
}

export function CustomGuardrailsEditor() {
  const rules = useGuardrails()
  const [editing, setEditing] = useState<Guardrail | 'new' | null>(null)
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Your guardrails</div>
        {editing === null && (
          <button type="button" className={buttonClasses} onClick={() => setEditing('new')}>
            Add guardrail
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-fg-muted">
        Checked against every argument a custom tool receives, in addition to the built-in guardrails above.
      </p>
      {editing !== null && (
        <div className="mt-3">
          <GuardrailForm initial={editing === 'new' ? null : editing} onDone={() => setEditing(null)} />
        </div>
      )}
      <ul className="mt-3 divide-y divide-line text-sm">
        {rules.list.data?.map((rule) => (
          <li key={rule.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div>
              <span className="font-medium">{rule.name}</span>{' '}
              <span className="font-mono text-xs text-fg-muted">
                {rule.kind === 'deny_regex' ? 'block' : 'require'} /{rule.pattern}/
              </span>
              <span className="ml-2 text-xs text-fg-subtle">
                {rule.applies_to === 'all' ? 'every tool' : 'custom and host-inspection tools'}
              </span>
              {!rule.enabled && <span className="ml-2 text-xs text-fg-subtle">disabled</span>}
              {rule.description && <div className="text-xs text-fg-muted">{rule.description}</div>}
            </div>
            <div className="flex gap-3">
              <button type="button" className={linkClasses}
                onClick={() => rules.save.mutate({ id: rule.id, input: { ...rule, enabled: !rule.enabled } })}>
                {rule.enabled ? 'Disable' : 'Enable'}
              </button>
              <button type="button" className={linkClasses} onClick={() => setEditing(rule)}>Edit</button>
              <button
                type="button"
                className="text-xs font-medium text-red-600 hover:underline"
                onClick={() => window.confirm(`Delete ${rule.name}?`) && rules.remove.mutate(rule.id)}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {rules.list.data?.length === 0 && <li className="py-2 text-fg-muted">No custom guardrails yet.</li>}
      </ul>
    </Card>
  )
}
