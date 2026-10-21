import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { ReportsPage } from './ReportsPage'

describe('ReportsPage', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('shows a report with its table and links the PDF download', async () => {
    const summary = { id: 3, title: 'Network report', source: 'snapshot', created_at: '2026-10-09T01:00:00Z' }
    server.use(
      http.get('/api/reports', () => HttpResponse.json([summary])),
      http.get('/api/reports/3', () =>
        HttpResponse.json({ ...summary, content: '## Devices\n\n| Name | IP |\n|---|---|\n| pve1 | 10.0.0.5 |\n' }),
      ),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <ReportsPage />
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('cell', { name: 'pve1' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download PDF' })).toHaveAttribute('href', '/api/reports/3/pdf')
  })

  it('creates a snapshot report on demand', async () => {
    let created = false
    server.use(
      http.get('/api/reports', () => HttpResponse.json([])),
      http.post('/api/reports/snapshot', () => {
        created = true
        return HttpResponse.json({ id: 1, title: 'New', source: 'snapshot', created_at: '2026-10-09T01:00:00Z', content: 'x' }, { status: 201 })
      }),
      http.get('/api/reports/1', () =>
        HttpResponse.json({ id: 1, title: 'New', source: 'snapshot', created_at: '2026-10-09T01:00:00Z', content: 'x' }),
      ),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <ReportsPage />
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Create report now' }))
    expect(await screen.findByRole('heading', { name: 'New' })).toBeInTheDocument()
    expect(created).toBe(true)
  })

  it('deletes all reports at once after confirming', async () => {
    const summary = { id: 3, title: 'Network report', source: 'snapshot', created_at: '2026-10-09T01:00:00Z' }
    let deletedAll = false
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      http.get('/api/reports', () => HttpResponse.json(deletedAll ? [] : [summary])),
      http.get('/api/reports/3', () =>
        HttpResponse.json({ ...summary, content: '## Devices\n\n| Name | IP |\n|---|---|\n| pve1 | 10.0.0.5 |\n' }),
      ),
      http.delete('/api/reports', () => {
        deletedAll = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <ReportsPage />
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Delete all' }))
    expect(window.confirm).toHaveBeenCalled()
    await screen.findByText('No reports yet.')
  })
})
