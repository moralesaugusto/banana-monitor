import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { AuthGate } from './AuthGate'

function renderGate() {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <p>the dashboard</p>
      </AuthGate>
    </QueryClientProvider>,
  )
}

describe('AuthGate', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('shows the login page when signed out and the app after signing in', async () => {
    let signedIn = false
    server.use(
      http.get('/api/auth/me', () =>
        signedIn
          ? HttpResponse.json({ username: 'admin', must_change_password: false })
          : new HttpResponse('{"detail":"Not signed in"}', { status: 401 }),
      ),
      http.post('/api/auth/login', async ({ request }) => {
        const body = (await request.json()) as { username: string; password: string }
        if (body.password !== 'right') return new HttpResponse('{"detail":"Wrong username or password"}', { status: 401 })
        signedIn = true
        return HttpResponse.json({ username: 'admin', must_change_password: false })
      }),
    )
    renderGate()

    const password = await screen.findByLabelText('Password')
    expect(screen.queryByText('the dashboard')).not.toBeInTheDocument()

    await userEvent.type(password, 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Wrong username or password')).toBeInTheDocument()

    await userEvent.clear(password)
    await userEvent.type(password, 'right')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('the dashboard')).toBeInTheDocument()
  })

  it('makes the default password be replaced before showing anything, with no complexity rules', async () => {
    let body: Record<string, string> = {}
    server.use(
      http.get('/api/auth/me', () => HttpResponse.json({ username: 'admin', must_change_password: true })),
      http.post('/api/auth/password', async ({ request }) => {
        body = (await request.json()) as Record<string, string>
        return HttpResponse.json({ username: 'admin', must_change_password: false })
      }),
    )
    renderGate()

    await screen.findByRole('heading', { name: 'Choose a new password' })
    expect(screen.queryByText('the dashboard')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Current password'), 'admin')
    await userEvent.type(screen.getByLabelText('New password'), 'x')
    await userEvent.type(screen.getByLabelText('Repeat new password'), 'y')
    expect(screen.getByText('The passwords do not match.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('Repeat new password'))
    await userEvent.type(screen.getByLabelText('Repeat new password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    await waitFor(() => expect(body).toEqual({ current_password: 'admin', new_password: 'x' }))
    expect(await screen.findByText('the dashboard')).toBeInTheDocument()
  })

  it('returns to the login page when a request finds the session has ended', async () => {
    server.use(
      http.get('/api/auth/me', () => HttpResponse.json({ username: 'admin', must_change_password: false })),
    )
    renderGate()
    expect(await screen.findByText('the dashboard')).toBeInTheDocument()

    queryClient.setQueryData(['auth', 'me'], null)
    expect(await screen.findByRole('heading', { name: 'Sign in to Banana' })).toBeInTheDocument()
  })
})
