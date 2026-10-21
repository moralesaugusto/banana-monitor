import type { AlertState } from '../api/alerts'
import { Badge, type BadgeTone } from './Badge'

const TONES: Record<AlertState, BadgeTone> = {
  ok: 'ok',
  pending: 'warn',
  firing: 'bad',
  resolved: 'info',
  flapping: 'purple',
}

export function AlertStateBadge({ state }: { state: AlertState }) {
  return <Badge tone={TONES[state]}>{state}</Badge>
}
