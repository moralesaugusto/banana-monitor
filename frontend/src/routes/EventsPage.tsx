import { useEvents } from '../api/events'
import type { EventSeverity } from '../api/events'
import { Badge, type BadgeTone } from '../components/Badge'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

const SEVERITY_TONES: Record<EventSeverity, BadgeTone> = {
  info: 'neutral',
  warning: 'warn',
  error: 'bad',
}

export function EventsPage() {
  const { data: events, isLoading } = useEvents()

  return (
    <div>
      <PageHeader
        title="Events"
        description="A chronological timeline of discovery, integration, and alert activity."
      />

      <div className="mt-6 overflow-x-auto">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Time</th>
                <th className="px-4 py-2.5 font-medium">Severity</th>
                <th className="px-4 py-2.5 font-medium">Category</th>
                <th className="px-4 py-2.5 font-medium">Message</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                    Loading…
                  </td>
                </tr>
              )}
              {events?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                    No events yet.
                  </td>
                </tr>
              )}
              {events?.map((event) => (
                <tr key={event.id} className="border-b border-line last:border-b-0">
                  <td className="px-4 py-2.5 whitespace-nowrap text-fg-muted">
                    {new Date(event.ts).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={SEVERITY_TONES[event.severity]}>{event.severity}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-fg-muted">{event.category}</td>
                  <td className="px-4 py-2.5">{event.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
