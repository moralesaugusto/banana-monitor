import { useAiModeTools } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { CustomGuardrailsEditor, CustomToolsEditor } from './CustomToolsEditor'
import { PageHeader } from '../../components/PageHeader'

export function AiToolsPage() {
  const { data } = useAiModeTools()
  return (
    <div>
      <PageHeader
        title="Tools and guardrails"
        description="A language model cannot run anything by itself. It can only ask for one of these tools; this application decides whether to allow it, runs it, and hands the result back."
      />
      {data && (
        <div className="mt-6 flex flex-col gap-6">
          <div className="grid gap-4 lg:grid-cols-3">
            {data.tools.map((tool) => (
              <Card key={tool.name} className="p-4">
                <div className="flex items-baseline justify-between">
                  <div className="font-mono text-sm font-medium">{tool.name}</div>
                  <span className={`text-xs ${tool.enabled ? 'text-emerald-600' : 'text-fg-muted'}`}>
                    {tool.enabled ? 'enabled' : 'disabled'}
                  </span>
                </div>
                <p className="mt-2 text-sm text-fg-muted">{tool.description}</p>
                <div className="mt-3 text-xs text-fg-muted">Schema the model sees</div>
                <pre className="mt-1 max-h-64 overflow-auto rounded-control bg-fg-subtle/10 p-2 font-mono text-xs">
                  {JSON.stringify(tool.parameters, null, 2)}
                </pre>
              </Card>
            ))}
          </div>

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

          <CustomToolsEditor />
          <CustomGuardrailsEditor />
        </div>
      )}
    </div>
  )
}
