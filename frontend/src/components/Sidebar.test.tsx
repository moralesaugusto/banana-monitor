import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { Sidebar } from './Sidebar'

function renderSidebar() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Sidebar collapsed={false} onToggleCollapsed={() => {}} mobileOpen={false} onNavigate={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Sidebar', () => {
  beforeEach(() => queryClient.clear())

  it('shows every Knowledge page once the knowledge base is on', async () => {
    server.use(http.get('/api/ai-mode/settings', () => HttpResponse.json({ knowledge_base_enabled: true })))
    const user = userEvent.setup()
    const { container } = renderSidebar()

    await user.click(await screen.findByRole('button', { name: /Knowledge/ }))

    expect(container.querySelector('a[href="/ai/knowledge"]')).toBeInTheDocument()
    expect(container.querySelector('a[href="/ai/knowledge/map"]')).toBeInTheDocument()
    expect(container.querySelector('a[href="/ai/knowledge/learn"]')).toBeInTheDocument()
    expect(container.querySelector('a[href="/ai/knowledge/settings"]')).toBeInTheDocument()
  })

  it('hides Browse/Map/How it works but keeps Settings reachable when the knowledge base is off', async () => {
    server.use(http.get('/api/ai-mode/settings', () => HttpResponse.json({ knowledge_base_enabled: false })))
    const user = userEvent.setup()
    const { container } = renderSidebar()

    await user.click(await screen.findByRole('button', { name: /Knowledge/ }))

    expect(container.querySelector('a[href="/ai/knowledge"]')).not.toBeInTheDocument()
    expect(container.querySelector('a[href="/ai/knowledge/map"]')).not.toBeInTheDocument()
    expect(container.querySelector('a[href="/ai/knowledge/learn"]')).not.toBeInTheDocument()
    expect(container.querySelector('a[href="/ai/knowledge/settings"]')).toBeInTheDocument()
  })
})
