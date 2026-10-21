import { useState } from 'react'
import type { DeviceListItem } from '../api/types'
import type { ParsedSchema } from '../lib/schemaForm'

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'

function UnsupportedField({
  fieldKey,
  value,
  onChange,
}: {
  fieldKey: string
  value: unknown
  onChange: (key: string, value: unknown) => void
}) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 0))
  const [invalid, setInvalid] = useState(false)

  return (
    <label className="flex flex-col text-sm sm:col-span-2">
      {fieldKey} <span className="text-xs text-fg-subtle">(raw JSON - unsupported field shape)</span>
      <textarea
        className={`${inputClasses} font-mono text-xs`}
        rows={2}
        value={text}
        onChange={(e) => {
          const next = e.target.value
          setText(next)
          try {
            onChange(fieldKey, JSON.parse(next))
            setInvalid(false)
          } catch {
            setInvalid(true)
          }
        }}
      />
      {invalid && <span className="mt-0.5 text-xs text-red-600">Must be valid JSON.</span>}
    </label>
  )
}

interface SchemaFieldsFormProps {
  parsed: ParsedSchema
  values: Record<string, unknown>
  onChange: (values: Record<string, unknown>) => void
  idPrefix: string
  /** When set, a `device_id` field (generic_ssh, windows_winrm) renders as a picker over these Devices
   * instead of a bare number input - there's no way to know a device's numeric id otherwise. */
  devices?: DeviceListItem[]
}

/** Renders one real input per schema field: text/number/checkbox/select. */
export function SchemaFieldsForm({ parsed, values, onChange, idPrefix, devices }: SchemaFieldsFormProps) {
  function setField(key: string, value: unknown) {
    onChange({ ...values, [key]: value })
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {parsed.fields.map((field) => {
        const id = `${idPrefix}-${field.key}`
        const value = values[field.key]

        if (field.key === 'device_id' && devices) {
          return (
            <label key={field.key} htmlFor={id} className="flex flex-col text-sm">
              Device
              <select
                id={id}
                className={inputClasses}
                value={value == null ? '' : String(value)}
                onChange={(e) => setField(field.key, e.target.value === '' ? undefined : Number(e.target.value))}
              >
                <option value="">— leave empty for a wallet credential —</option>
                {devices.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.display_name}
                    {device.primary_ip ? ` (${device.primary_ip})` : ''}
                  </option>
                ))}
              </select>
              <span className="text-xs text-fg-subtle">
                The existing Device this host belongs to. Leave empty, with Host also empty, to save this
                credential in the wallet instead.
              </span>
            </label>
          )
        }

        if (field.kind === 'boolean') {
          return (
            <label key={field.key} htmlFor={id} className="flex items-center gap-2 self-end py-1.5 text-sm">
              <input
                id={id}
                type="checkbox"
                checked={Boolean(value)}
                onChange={(e) => setField(field.key, e.target.checked)}
                className="h-4 w-4 rounded border-line-strong accent-current text-accent"
              />
              {field.title}
              {field.required && <span className="text-red-500">*</span>}
            </label>
          )
        }

        if (field.kind === 'enum') {
          return (
            <label key={field.key} htmlFor={id} className="flex flex-col text-sm">
              {field.title}
              {field.required && <span className="text-red-500">*</span>}
              <select
                id={id}
                className={inputClasses}
                value={value != null ? String(value) : ''}
                onChange={(e) => setField(field.key, e.target.value)}
              >
                <option value="" disabled={field.required}>
                  Select…
                </option>
                {field.enumValues?.map((option) => (
                  <option key={String(option)} value={String(option)}>
                    {String(option)}
                  </option>
                ))}
              </select>
              {field.description && <span className="text-xs text-fg-subtle">{field.description}</span>}
            </label>
          )
        }

        if (field.kind === 'integer' || field.kind === 'number') {
          return (
            <label key={field.key} htmlFor={id} className="flex flex-col text-sm">
              {field.title}
              {field.required && <span className="text-red-500">*</span>}
              <input
                id={id}
                type="number"
                step={field.kind === 'integer' ? 1 : 'any'}
                className={inputClasses}
                value={value == null ? '' : String(value)}
                onChange={(e) => {
                  const raw = e.target.value
                  setField(field.key, raw === '' ? undefined : Number(raw))
                }}
              />
              {field.description && <span className="text-xs text-fg-subtle">{field.description}</span>}
            </label>
          )
        }

        return (
          <label key={field.key} htmlFor={id} className="flex flex-col text-sm">
            {field.title}
            {field.required && <span className="text-red-500">*</span>}
            <input
              id={id}
              type="text"
              className={inputClasses}
              value={value == null ? '' : String(value)}
              onChange={(e) => setField(field.key, e.target.value)}
            />
            {field.description && <span className="text-xs text-fg-subtle">{field.description}</span>}
          </label>
        )
      })}

      {parsed.unsupportedKeys.map((key) => (
        <UnsupportedField key={key} fieldKey={key} value={values[key]} onChange={setField} />
      ))}
    </div>
  )
}
