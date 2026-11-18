import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'
import { queryClient } from './lib/queryClient'
import { server } from './test/mswServer'

describe('App', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(http.get('/api/auth/me', () => HttpResponse.json({ username: 'admin', must_change_password: false })))
  })

  it('renders the overview page with navigation and a healthy status', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Devices' })).toBeInTheDocument()
    expect(await screen.findByText('Platform healthy')).toBeInTheDocument()
  })

  it('opens Credentials & Keys as one page with Credentials and How it works reachable from it', async () => {
    server.use(
      http.get('/api/integrations/types', () => HttpResponse.json([])),
      http.get('/api/credentials', () => HttpResponse.json([])),
      http.get('/api/integrations', () => HttpResponse.json([])),
    )
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Overview' })

    await user.click(screen.getByRole('link', { name: 'Credentials & Keys' }))
    expect(await screen.findByRole('heading', { name: 'Credentials & Keys' })).toBeInTheDocument()
    expect(await screen.findByText('No integrations configured yet.')).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Credentials' }))
    expect(await screen.findByText('No credentials saved yet.')).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'How it works' }))
    expect(await screen.findByRole('heading', { name: 'How integrations work' })).toBeInTheDocument()
  })
})
