import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthGate } from './components/AuthGate'
import { AppShell } from './components/AppShell'
import { queryClient } from './lib/queryClient'
import { AuditPage } from './routes/AuditPage'
import { AboutPage } from './routes/AboutPage'
import { CredentialsPage } from './routes/CredentialsPage'
import { AgentEditPage } from './routes/ai/AgentEditPage'
import { AgentsPage } from './routes/ai/AgentsPage'
import { AiMapPage } from './routes/ai/AiMapPage'
import { MessagesPage } from './routes/ai/MessagesPage'
import { AiConfigPage } from './routes/ai/AiConfigPage'
import { AiLearnPage } from './routes/ai/AiLearnPage'
import { AiRunPage } from './routes/ai/AiRunPage'
import { AiRunsPage } from './routes/ai/AiRunsPage'
import { BusPage } from './routes/ai/BusPage'
import { WorkflowPage } from './routes/ai/WorkflowPage'
import { AiToolsPage } from './routes/ai/AiToolsPage'
import { AiTracePage } from './routes/ai/AiTracePage'
import { AlertsPage } from './routes/AlertsPage'
import { DeviceDetailPage } from './routes/DeviceDetailPage'
import { DevicesPage } from './routes/DevicesPage'
import { DiscoveryPage } from './routes/DiscoveryPage'
import { EventsPage } from './routes/EventsPage'
import { IntegrationsLearnPage } from './routes/IntegrationsLearnPage'
import { IntegrationsPage } from './routes/IntegrationsPage'
import { NetworkGraphPage } from './routes/NetworkGraphPage'
import { NetworkMapPage } from './routes/NetworkMapPage'
import { NetworksPage } from './routes/NetworksPage'
import { OverviewPage } from './routes/OverviewPage'
import { ReportsPage } from './routes/ReportsPage'
import { ServicesPage } from './routes/ServicesPage'
import { SystemPage } from './routes/SystemPage'

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<OverviewPage />} />
            <Route path="devices" element={<DevicesPage />} />
            <Route path="devices/:id" element={<DeviceDetailPage />} />
            <Route path="services" element={<ServicesPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="network-map" element={<NetworkGraphPage />} />
            <Route path="ai" element={<AiRunPage />} />
            <Route path="ai/runs" element={<AiRunsPage />} />
            <Route path="ai/runs/:id" element={<AiTracePage />} />
            <Route path="ai/agents" element={<AgentsPage />} />
            <Route path="ai/agents/new" element={<AgentEditPage />} />
            <Route path="ai/agents/:name" element={<AgentsPage />} />
            <Route path="ai/agents/:name/edit" element={<AgentEditPage />} />
            <Route path="ai/workflow" element={<WorkflowPage />} />
            <Route path="ai/messages" element={<MessagesPage />} />
            <Route path="ai/bus" element={<BusPage />} />
            <Route path="ai/map" element={<AiMapPage />} />
            <Route path="ai/config" element={<AiConfigPage />} />
            <Route path="ai/tools" element={<AiToolsPage />} />
            <Route path="ai/learn" element={<AiLearnPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="events" element={<EventsPage />} />
            <Route path="discovery" element={<DiscoveryPage />} />
            <Route path="integrations" element={<IntegrationsPage />} />
            <Route path="integrations/credentials" element={<CredentialsPage />} />
            <Route path="integrations/learn" element={<IntegrationsLearnPage />} />
            <Route path="networks" element={<NetworksPage />} />
            <Route path="networks/:id/map" element={<NetworkMapPage />} />
            <Route path="system" element={<SystemPage />} />
            <Route path="about" element={<AboutPage />} />
            <Route path="about/audit" element={<AuditPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </AuthGate>
    </QueryClientProvider>
  )
}

export default App
