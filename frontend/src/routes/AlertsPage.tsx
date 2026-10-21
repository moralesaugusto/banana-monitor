import { useState } from 'react'
import {
  ALERT_CONDITION_TYPES,
  useAlertRules,
  useAlertStates,
  useCreateAlertRule,
  useDeleteAlertRule,
  useUpdateAlertRule,
  type AlertConditionType,
  type AlertSeverity,
} from '../api/alerts'
import { AlertStateBadge } from '../components/AlertStateBadge'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

const CONDITION_HINTS: Record<AlertConditionType, string> = {
  device_down: '{"staleness_seconds": 90, "for_duration_seconds": 60}',
  service_down: '{"staleness_seconds": 90, "for_duration_seconds": 60}',
  high_cpu: '{"threshold": 90, "for_duration_seconds": 60}',
  high_memory: '{"threshold": 90, "for_duration_seconds": 60}',
  disk_usage_high: '{"threshold": 90, "for_duration_seconds": 60}',
  integration_failing: '{"for_duration_seconds": 60}',
  metric_threshold: '{"entity_type": "device", "metric_name": "cpu_percent", "comparator": ">", "threshold": 90}',
}

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const primaryButtonClasses =
  'self-start rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

export function AlertsPage() {
  const { data: states, isLoading: statesLoading } = useAlertStates()
  const { data: rules, isLoading: rulesLoading } = useAlertRules()
  const createRule = useCreateAlertRule()
  const updateRule = useUpdateAlertRule()
  const deleteRule = useDeleteAlertRule()

  const [name, setName] = useState('')
  const [conditionType, setConditionType] = useState<AlertConditionType>('device_down')
  const [severity, setSeverity] = useState<AlertSeverity>('warning')
  const [parametersText, setParametersText] = useState(CONDITION_HINTS.device_down)
  const [error, setError] = useState<string | null>(null)

  function handleConditionChange(value: AlertConditionType) {
    setConditionType(value)
    setParametersText(CONDITION_HINTS[value])
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    if (!name) return

    let parameters: Record<string, unknown>
    try {
      parameters = JSON.parse(parametersText)
    } catch {
      setError('Parameters must be valid JSON.')
      return
    }

    createRule.mutate(
      { name, condition_type: conditionType, severity, parameters },
      { onSuccess: () => setName(''), onError: () => setError('Failed to create rule.') },
    )
  }

  return (
    <div>
      <PageHeader
        title="Alerts"
        description="Rules define what counts as broken. Active alerts show devices/services/integrations currently pending, firing, resolved, or flapping."
      />

      <section className="mt-6">
        <h2 className="text-lg font-semibold text-fg">Active alerts</h2>
        <div className="mt-2 overflow-x-auto">
          <Card className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line text-fg-muted">
                  <th className="px-4 py-2.5 font-medium">Entity</th>
                  <th className="px-4 py-2.5 font-medium">State</th>
                  <th className="px-4 py-2.5 font-medium">Value</th>
                  <th className="px-4 py-2.5 font-medium">Changed</th>
                </tr>
              </thead>
              <tbody>
                {statesLoading && (
                  <tr>
                    <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                      Loading…
                    </td>
                  </tr>
                )}
                {states?.length === 0 && (
                  <tr>
                    <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                      Nothing broken right now.
                    </td>
                  </tr>
                )}
                {states?.map((state) => (
                  <tr key={state.id} className="border-b border-line last:border-b-0">
                    <td className="px-4 py-2.5">
                      {state.entity_type} #{state.entity_id}
                    </td>
                    <td className="px-4 py-2.5">
                      <AlertStateBadge state={state.state} />
                    </td>
                    <td className="px-4 py-2.5 font-mono tabular-nums text-fg-muted">
                      {state.current_value?.toFixed(2) ?? '—'}
                    </td>
                    <td className="px-4 py-2.5 text-fg-muted">
                      {new Date(state.state_changed_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="text-lg font-semibold text-fg">Rules</h2>

        <form onSubmit={handleSubmit} className="mt-4 flex max-w-2xl flex-col gap-3 rounded-card border border-line bg-surface p-4">
          <div className="flex flex-wrap gap-3">
            <label className="flex flex-1 flex-col text-sm">
              Name
              <input
                className={inputClasses}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="device down"
              />
            </label>
            <label className="flex flex-1 flex-col text-sm">
              Condition
              <select
                className={inputClasses}
                value={conditionType}
                onChange={(e) => handleConditionChange(e.target.value as AlertConditionType)}
              >
                {ALERT_CONDITION_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-1 flex-col text-sm">
              Severity
              <select
                className={inputClasses}
                value={severity}
                onChange={(e) => setSeverity(e.target.value as AlertSeverity)}
              >
                <option value="critical">critical</option>
                <option value="warning">warning</option>
                <option value="info">info</option>
              </select>
            </label>
          </div>

          <label className="flex flex-col text-sm">
            Parameters (JSON)
            <textarea
              className={`${inputClasses} font-mono text-xs`}
              rows={2}
              value={parametersText}
              onChange={(e) => setParametersText(e.target.value)}
            />
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button type="submit" disabled={createRule.isPending} className={primaryButtonClasses}>
            Add rule
          </button>
        </form>

        <div className="mt-4 overflow-x-auto">
          <Card className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line text-fg-muted">
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 font-medium">Condition</th>
                  <th className="px-4 py-2.5 font-medium">Severity</th>
                  <th className="px-4 py-2.5 font-medium">Enabled</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {rulesLoading && (
                  <tr>
                    <td className="px-4 py-3 text-fg-muted" colSpan={5}>
                      Loading…
                    </td>
                  </tr>
                )}
                {rules?.length === 0 && (
                  <tr>
                    <td className="px-4 py-3 text-fg-muted" colSpan={5}>
                      No rules yet.
                    </td>
                  </tr>
                )}
                {rules?.map((rule) => (
                  <tr key={rule.id} className="border-b border-line last:border-b-0">
                    <td className="px-4 py-2.5 font-medium">{rule.name}</td>
                    <td className="px-4 py-2.5 text-fg-muted">{rule.condition_type}</td>
                    <td className="px-4 py-2.5 text-fg-muted">{rule.severity}</td>
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        checked={rule.enabled}
                        onChange={(e) => updateRule.mutate({ id: rule.id, enabled: e.target.checked })}
                        className="h-4 w-4 rounded border-line-strong accent-current text-accent"
                      />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => deleteRule.mutate(rule.id)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      </section>
    </div>
  )
}
