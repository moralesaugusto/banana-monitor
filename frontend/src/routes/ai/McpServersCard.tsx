import { useState } from 'react'
import {
  type CustomTool,
  type McpImportResult,
  type McpServer,
  type McpTestResult,
  type ToolTestResult,
  useCustomTools,
  useDeleteMcpServer,
  useImportMcpTools,
  useMcpServers,
  useSaveMcpServer,
  useTestCustomTool,
  useTestMcpConnection,
} from '../../api/aiMode'
import { Card } from '../../components/Card'
import { TestResult } from './CustomToolsEditor'

const inputClasses = 'mt-1 w-full rounded-control border border-line bg-surface px-2 py-1 text-sm'
const buttonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50'
const linkClasses = 'text-xs font-medium text-accent-strong hover:underline disabled:opacity-50'

function TestOutcome({ result }: { result: McpTestResult }) {
  if (!result.ok) return <p className="mt-2 text-xs text-red-600">Connection failed: {result.detail}</p>
  const who = [result.server_name, result.server_version].filter(Boolean).join(' ')
  return (
    <div className="mt-2 text-xs text-emerald-600">
      Connected{who && ` to ${who}`} in {result.duration_ms} ms. It offers {result.tool_count} tool(s).
      <div className="mt-1 font-mono text-fg-muted">
        {result.tool_names.join(', ')}
        {result.tool_count > result.tool_names.length && ', ...'}
      </div>
    </div>
  )
}

function ImportOutcome({ result }: { result: McpImportResult }) {
  return (
    <div className="mt-1 text-xs">
      <span className="text-emerald-600">
        Imported: {result.added} added, {result.updated} updated, {result.removed} removed.
      </span>
      {result.unscoped.length > 0 && (
        <p className="mt-1 text-amber-600">
          {result.unscoped.length} tool(s) take no target, ip or host argument, so the check that keeps a call
          inside your networks cannot cover them: {result.unscoped.slice(0, 8).join(', ')}
          {result.unscoped.length > 8 && ', ...'}. Only give them to an agent you trust with that.
        </p>
      )}
    </div>
  )
}

function AddServerForm() {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const save = useSaveMcpServer()
  const test = useTestMcpConnection()
  const imports = useImportMcpTools()
  const [outcome, setOutcome] = useState<McpImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function add(importNow: boolean) {
    setError(null)
    setOutcome(null)
    try {
      const server = await save.mutateAsync({ input: { name, url } })
      if (importNow) setOutcome(await imports.mutateAsync({ id: server.id, removeMissing: false }))
      setName('')
      setUrl('')
      test.reset()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const busy = save.isPending || imports.isPending
  return (
    <div className="mt-3 rounded-control bg-canvas p-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-xs text-fg-muted">
          Name
          <input
            className={`${inputClasses} w-44`}
            placeholder="HexStrike"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="flex flex-col text-xs text-fg-muted">
          Server address
          <input
            className={`${inputClasses} w-80 font-mono`}
            placeholder="http://10.0.0.10:8891/mcp"
            value={url}
            onChange={(e) => {
              test.reset()
              setUrl(e.target.value)
            }}
          />
        </label>
        <button type="button" className={buttonClasses} disabled={!url || test.isPending} onClick={() => test.mutate(url)}>
          {test.isPending ? 'Testing...' : 'Test connection'}
        </button>
        <button type="button" className={buttonClasses} disabled={!name || !url || busy} onClick={() => void add(true)}>
          {busy ? 'Adding...' : 'Add and import tools'}
        </button>
        <button type="button" className={buttonClasses} disabled={!name || !url || busy} onClick={() => void add(false)}>
          Add only
        </button>
      </div>
      {test.data && <TestOutcome result={test.data} />}
      {test.isError && <p className="mt-2 text-xs text-red-600">{test.error.message}</p>}
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      {outcome && <ImportOutcome result={outcome} />}
    </div>
  )
}

function ServerTools({ tools }: { tools: CustomTool[] }) {
  const [results, setResults] = useState<Record<number, ToolTestResult>>({})
  const test = useTestCustomTool()
  return (
    <ul className="mt-2 divide-y divide-line rounded-control bg-canvas px-3 text-sm">
      {tools.map((tool) => (
        <li key={tool.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
          <div className="min-w-0 flex-1">
            <span className="font-mono font-medium">{tool.name}</span>
            <div className="text-xs text-fg-muted">{tool.description}</div>
            <TestResult result={results[tool.id]} />
          </div>
          <button
            type="button"
            className={linkClasses}
            disabled={test.isPending && test.variables === tool.id}
            onClick={() => test.mutate(tool.id, { onSuccess: (r) => setResults((prev) => ({ ...prev, [tool.id]: r })) })}
          >
            {test.isPending && test.variables === tool.id ? 'Testing...' : 'Test'}
          </button>
        </li>
      ))}
    </ul>
  )
}

function ServerRow({ server }: { server: McpServer }) {
  const [open, setOpen] = useState(false)
  const tools = (useCustomTools().list.data ?? []).filter((t) => t.mcp_server_id === server.id)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(server.name)
  const [url, setUrl] = useState(server.url)
  const [removeMissing, setRemoveMissing] = useState(false)
  const [outcome, setOutcome] = useState<McpImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const save = useSaveMcpServer()
  const test = useTestMcpConnection()
  const imports = useImportMcpTools()
  const remove = useDeleteMcpServer()

  function fail(e: Error) {
    setError(e.message)
  }

  function runImport() {
    setError(null)
    imports.mutate({ id: server.id, removeMissing }, { onSuccess: setOutcome, onError: fail })
  }

  function deleteAll() {
    const message = `Delete the MCP server "${server.name}" and its ${server.tool_count} imported tool(s)? ` +
      'They are also taken off every agent. This cannot be undone.'
    if (!window.confirm(message)) return
    setError(null)
    remove.mutate(server.id, { onError: fail })
  }

  return (
    <li className="py-3 text-sm">
      {editing ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            setError(null)
            save.mutate({ id: server.id, input: { name, url } }, { onSuccess: () => setEditing(false), onError: fail })
          }}
        >
          <input aria-label="Edit server name" className={`${inputClasses} w-44`} value={name} onChange={(e) => setName(e.target.value)} />
          <input aria-label="Edit server address" className={`${inputClasses} w-80 font-mono`} value={url} onChange={(e) => setUrl(e.target.value)} />
          <button type="submit" className={buttonClasses} disabled={save.isPending || !name || !url}>
            Save
          </button>
          <button type="button" className={buttonClasses} onClick={() => setEditing(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <span className="font-medium">{server.name}</span>{' '}
            <span className="font-mono text-xs text-fg-muted">{server.url}</span>
            <button
              type="button"
              className="text-xs text-fg-muted hover:underline"
              aria-expanded={open}
              disabled={server.tool_count === 0}
              onClick={() => setOpen(!open)}
            >
              {open ? 'Hide' : 'Show'} {server.tool_count} imported tool(s)
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1 text-xs text-fg-muted">
              <input type="checkbox" checked={removeMissing} onChange={(e) => setRemoveMissing(e.target.checked)} />
              Remove tools it no longer offers
            </label>
            <button type="button" className={linkClasses} disabled={test.isPending} onClick={() => test.mutate(server.url)}>
              {test.isPending ? 'Testing...' : 'Test connection'}
            </button>
            <button type="button" className={linkClasses} disabled={imports.isPending} onClick={runImport}>
              {imports.isPending ? 'Importing...' : server.tool_count ? 'Refresh tools' : 'Import tools'}
            </button>
            <button type="button" className={linkClasses} onClick={() => setEditing(true)}>
              Edit
            </button>
            <button
              type="button"
              className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50"
              disabled={remove.isPending}
              onClick={deleteAll}
            >
              Delete server and tools
            </button>
          </div>
        </div>
      )}
      {open && <ServerTools tools={tools} />}
      {test.data && <TestOutcome result={test.data} />}
      {outcome && <ImportOutcome result={outcome} />}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </li>
  )
}

/** Add an MCP server by address, check it answers, import every tool it offers, and remove the server
 * together with those tools in one step. */
export function McpServersCard() {
  const servers = useMcpServers()
  return (
    <Card className="p-4">
      <div className="text-sm font-medium">MCP servers</div>
      <p className="mt-1 text-xs text-fg-muted">
        Give the address of an MCP server (streamable HTTP, no authentication) and Banana imports every tool it
        offers, listed under that server. Importing never turns a tool on for an agent; do that under Agents.
        Refresh picks up tools the server added or changed.
      </p>
      <AddServerForm />
      <ul className="mt-2 divide-y divide-line">
        {servers.data?.map((server) => <ServerRow key={`${server.id}:${server.name}:${server.url}`} server={server} />)}
        {servers.data?.length === 0 && <li className="py-2 text-sm text-fg-muted">No MCP servers yet.</li>}
      </ul>
    </Card>
  )
}
