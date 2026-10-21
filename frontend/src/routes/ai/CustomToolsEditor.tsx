import { useState } from 'react'
import {
  type CustomTool,
  type CustomToolInput,
  type Guardrail,
  type GuardrailInput,
  useCustomTools,
  useGuardrails,
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
  const [paramsText, setParamsText] = useState(JSON.stringify(initial?.parameters ?? {}, null, 2))
  const [error, setError] = useState<string | null>(null)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    let parameters: Record<string, unknown> = {}
    if (draft.kind === 'mcp') {
      try {
        parameters = JSON.parse(paramsText || '{}')
      } catch {
        setError('Parameters must be valid JSON')
        return
      }
    }
    const input: CustomToolInput = {
      ...draft,
      command: draft.kind === 'command' ? commandText.split(/\s+/).filter(Boolean) : [],
      mcp_url: draft.kind === 'mcp' ? draft.mcp_url : null,
      mcp_tool: draft.kind === 'mcp' ? draft.mcp_tool : null,
      parameters,
    }
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
      <div className="grid gap-3 sm:grid-cols-2">
        <label>
          Name
          <input className={inputClasses} value={draft.name} placeholder="whatweb_scan"
            onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <label>
          Kind
          <select className={inputClasses} value={draft.kind}
            onChange={(e) => setDraft({ ...draft, kind: e.target.value as CustomTool['kind'] })}>
            <option value="command">Local command</option>
            <option value="mcp">MCP server tool</option>
          </select>
        </label>
      </div>
      <label>
        Description the model sees
        <input className={inputClasses} value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      </label>
      {draft.kind === 'command' ? (
        <label>
          Command (no shell; {'{target}'} and {'{port}'} are substituted)
          <input className={`${inputClasses} font-mono`} value={commandText} placeholder="whatweb --no-errors {target}"
            onChange={(e) => setCommandText(e.target.value)} />
        </label>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              MCP server URL
              <input className={`${inputClasses} font-mono`} value={draft.mcp_url ?? ''} placeholder="http://192.168.1.20:8000/mcp"
                onChange={(e) => setDraft({ ...draft, mcp_url: e.target.value })} />
            </label>
            <label>
              Tool name on the server
              <input className={`${inputClasses} font-mono`} value={draft.mcp_tool ?? ''}
                onChange={(e) => setDraft({ ...draft, mcp_tool: e.target.value })} />
            </label>
          </div>
          <label>
            Parameters (JSON schema shown to the model)
            <textarea className={`${inputClasses} h-28 font-mono text-xs`} value={paramsText}
              onChange={(e) => setParamsText(e.target.value)} />
          </label>
        </>
      )}
    </form>
  )
}

function GuardrailForm({ initial, onDone }: { initial: Guardrail | null; onDone: () => void }) {
  const { save } = useGuardrails()
  const [draft, setDraft] = useState<GuardrailInput>(
    initial ?? { name: '', description: '', kind: 'deny_regex', pattern: '', enabled: true },
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
        Description
        <input className={inputClasses} value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      </label>
    </form>
  )
}

export function CustomToolsEditor() {
  const tools = useCustomTools()
  const [editing, setEditing] = useState<CustomTool | 'new' | null>(null)
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Your tools (local commands and MCP servers)</div>
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
      {editing !== null && (
        <div className="mt-3">
          <ToolForm initial={editing === 'new' ? null : editing} onDone={() => setEditing(null)} />
        </div>
      )}
      <ul className="mt-3 divide-y divide-line text-sm">
        {tools.list.data?.map((tool) => (
          <li key={tool.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div>
              <span className="font-mono font-medium">{tool.name}</span>{' '}
              <span className="text-xs text-fg-muted">
                {tool.kind === 'mcp' ? `MCP ${tool.mcp_url}` : tool.command.join(' ')}
              </span>
              <div className="text-xs text-fg-muted">{tool.description}</div>
            </div>
            <div className="flex gap-3">
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
        {tools.list.data?.length === 0 && <li className="py-2 text-fg-muted">No custom tools yet.</li>}
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
