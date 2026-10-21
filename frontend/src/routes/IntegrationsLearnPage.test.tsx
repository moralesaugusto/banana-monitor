import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { IntegrationTypeInfo } from '../api/integrations'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { IntegrationsLearnPage } from './IntegrationsLearnPage'

const TYPES: IntegrationTypeInfo[] = [
  { type_key: 'generic_ssh', display_name: 'Generic (SSH)', config_schema: {}, credential_schema: {} },
  { type_key: 'http_tcp', display_name: 'HTTP/HTTPS/TCP', config_schema: {}, credential_schema: null },
]

describe('IntegrationsLearnPage', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('renders a card per registered plugin type and explains the wallet', async () => {
    server.use(http.get('/api/integrations/types', () => HttpResponse.json(TYPES)))

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <IntegrationsLearnPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Generic (SSH)')).toBeInTheDocument()
    expect(screen.getByText('HTTP/HTTPS/TCP')).toBeInTheDocument()
    expect(screen.getByText('The credential wallet')).toBeInTheDocument()
    expect(screen.getByText('What it is')).toBeInTheDocument()
  })
})
