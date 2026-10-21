export type DeviceType =
  | 'linux'
  | 'windows'
  | 'proxmox_node'
  | 'proxmox_vm'
  | 'proxmox_lxc'
  | 'network_equipment'
  | 'platform_self'
  | 'other'

export type HealthStatus = 'up' | 'down' | 'degraded' | 'unknown'

export type ServiceType =
  | 'http'
  | 'https'
  | 'tcp'
  | 'dns'
  | 'dhcp'
  | 'proxmox_vm'
  | 'proxmox_lxc'
  | 'systemd_unit'

export const DEVICE_TYPES: DeviceType[] = [
  'linux',
  'windows',
  'proxmox_node',
  'proxmox_vm',
  'proxmox_lxc',
  'network_equipment',
  'other',
]

export const SERVICE_TYPES: ServiceType[] = [
  'http',
  'https',
  'tcp',
  'dns',
  'dhcp',
  'proxmox_vm',
  'proxmox_lxc',
  'systemd_unit',
]

export interface Network {
  id: number
  site_id: number
  name: string
  cidr: string
  vlan_id: number | null
  description: string | null
}

export interface NetworkCreate {
  name: string
  cidr: string
  vlan_id?: number | null
  description?: string | null
}

export interface Device {
  id: number
  site_id: number
  network_id: number | null
  hostname: string | null
  display_name: string
  primary_ip: string | null
  device_type: DeviceType
  status: HealthStatus
  managed: boolean
  tags: string[]
  notes: string | null
  first_seen_at: string
  last_seen_at: string | null
  inactive: boolean
}

export interface DeviceListItem extends Device {
  role?: string
  vendor?: string | null
  network_name?: string | null
  service_count?: number
  services_up?: number
}

export interface DeviceCreate {
  display_name: string
  device_type: DeviceType
  hostname?: string | null
  primary_ip?: string | null
  network_id?: number | null
  tags?: string[]
  notes?: string | null
}

export interface DeviceAddress {
  id: number
  ip_address: string
  mac_address: string | null
  is_primary: boolean
  vendor: string | null
}

export interface DeviceServiceSummary {
  id: number
  name: string
  service_type: ServiceType
  status: HealthStatus
}

export interface DeviceDetail extends Device {
  addresses: DeviceAddress[]
  services: DeviceServiceSummary[]
  metrics: Record<string, number>
}

export interface MetricPoint {
  ts: string
  value: number
}

export interface Service {
  id: number
  device_id: number | null
  name: string
  service_type: ServiceType
  config: Record<string, unknown>
  status: HealthStatus
  managed: boolean
  port: number | null
  source: string
  fingerprint: ServiceFingerprint | null
  last_checked_at: string | null
  last_latency_ms: number | null
  device_vendor: string | null
}

export interface ServiceFingerprint {
  name?: string
  product?: string
  version?: string
  extrainfo?: string
  banner?: string
  notes?: string
  source?: string
  fingerprinted_at?: string
}

export interface ServiceCreate {
  name: string
  service_type: ServiceType
  device_id?: number | null
  config?: Record<string, unknown>
}
