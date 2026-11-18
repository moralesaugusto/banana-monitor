import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { KnowledgeMapPage } from './KnowledgeMapPage'

const points = [
  { entry_id: 1, title: 'Fail2ban note', collection_id: 1, collection_name: 'LAN notes', x: -1.0, y: 0.5 },
  { entry_id: 2, title: 'CVE writeup', collection_id: 2, collection_name: 'Security knowledge', x: 1.0, y: -0.5 },
]

function Where() {
  return <div data-testid="where">{useLocation().pathname + useLocation().search}</div>
}

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<KnowledgeMapPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('KnowledgeMapPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(http.get('/api/knowledge/projection', () => HttpResponse.json(points)))
  })

  it('plots one point per entry, colored and legended by collection', async () => {
    renderPage()

    expect(await screen.findByText('LAN notes')).toBeInTheDocument()
    expect(screen.getByText('Security knowledge')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Knowledge embedding map' })).toBeInTheDocument()
  })

  it('shows an empty-state message with no entries', async () => {
    server.use(http.get('/api/knowledge/projection', () => HttpResponse.json([])))
    renderPage()

    expect(await screen.findByText(/No entries yet/)).toBeInTheDocument()
  })

  it('opens the entry on Browse when a point is clicked', async () => {
    const user = userEvent.setup()
    renderPage()

    const point = await screen.findByRole('button', { name: 'Fail2ban note (LAN notes)' })
    await user.click(point)

    expect(screen.getByTestId('where')).toHaveTextContent('/ai/knowledge?entry=1')
  })
})
