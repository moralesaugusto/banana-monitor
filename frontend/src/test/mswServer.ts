import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const server = setupServer(
  http.get('/api/health', () => HttpResponse.json({ status: 'ok' })),
  http.get('/api/maintenance/counts', () =>
    HttpResponse.json({ reports: 0, events: 0, alerts: 0, bus: 0, history: 0, ai_runs: 0, audit: 0 }),
  ),
  http.get('/api/overview', () =>
    HttpResponse.json({
      devices: { up: 0, down: 0, degraded: 0, unknown: 0 },
      services: { up: 0, down: 0, degraded: 0, unknown: 0 },
      integrations_ok: 0,
      integrations_error: 0,
      firing_alerts: [],
      recent_events: [],
    }),
  ),
  // ChatPanel is mounted globally in AppShell and fetches its message list on
  // every render regardless of open/closed state, so every test that renders
  // AppShell (directly or via App) needs this mocked - not just ChatPanel's
  // own tests.
  http.get('/api/assistant/messages', () => HttpResponse.json([])),
  // The top bar shows the continuous-loop indicator on every page.
  http.get('/api/ai-mode/status', () =>
    HttpResponse.json({
      ai_enabled: false,
      run: null,
      last_run: null,
      agents: [],
      schedule: {
        schedule_enabled: false,
        schedule_interval_seconds: 21600,
        schedule_entry_agent: 'discoverer',
        max_run_minutes: 30,
        max_targets: 25,
        llm_call_timeout_seconds: 120,
        last_scheduled_at: null,
        next_run_at: null,
      },
    }),
  ),
)
