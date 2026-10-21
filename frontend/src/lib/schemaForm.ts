type PrimitiveKind = 'string' | 'integer' | 'number' | 'boolean'

export interface SchemaField {
  key: string
  title: string
  description?: string
  required: boolean
  kind: PrimitiveKind | 'enum'
  enumValues?: (string | number)[]
  default?: unknown
}

export interface ParsedSchema {
  fields: SchemaField[]
  /** Property keys present in the schema whose shape we don't confidently
   * support (nested object/array, $ref, oneOf, multi-type anyOf, ...). */
  unsupportedKeys: string[]
}

interface JsonSchemaLike {
  type?: string
  properties?: Record<string, JsonSchemaPropertyLike>
  required?: string[]
}

interface JsonSchemaPropertyLike {
  type?: string
  title?: string
  description?: string
  default?: unknown
  enum?: (string | number)[]
  anyOf?: JsonSchemaPropertyLike[]
}

const PRIMITIVE_KINDS: PrimitiveKind[] = ['string', 'integer', 'number', 'boolean']

function resolvePrimitive(
  prop: JsonSchemaPropertyLike,
): { kind: SchemaField['kind']; enumValues?: (string | number)[] } | null {
  if (Array.isArray(prop.enum) && prop.enum.length > 0) {
    return { kind: 'enum', enumValues: prop.enum }
  }
  if (typeof prop.type === 'string') {
    return PRIMITIVE_KINDS.includes(prop.type as PrimitiveKind) ? { kind: prop.type as PrimitiveKind } : null
  }
  if (Array.isArray(prop.anyOf)) {
    // The common "optional field" shape pydantic emits: {anyOf: [{type: X}, {type: "null"}]}.
    const nonNull = prop.anyOf.filter((branch) => branch.type !== 'null')
    if (nonNull.length === 1 && prop.anyOf.length === 2) {
      return resolvePrimitive(nonNull[0])
    }
  }
  return null
}

/**
 * Reduces a flat-ish JSON Schema object (as produced by Pydantic's
 * `model_json_schema()`) into a list of renderable fields, for the six
 * plugins this app ships with today (http_tcp, generic_ssh, proxmox,
 * adguard_home, homebridge, omada) plus dns/dhcp - all flat string/number/
 * boolean/enum shapes, no nesting. Anything else (object/array/$ref/oneOf)
 * is reported back in `unsupportedKeys` so the caller can fall back to a
 * raw-JSON textarea for just that field.
 */
export function parseObjectSchema(schema: unknown): ParsedSchema | null {
  if (!schema || typeof schema !== 'object') return null
  const s = schema as JsonSchemaLike
  if (s.type && s.type !== 'object') return null
  if (!s.properties || Object.keys(s.properties).length === 0) return null

  const required = new Set(s.required ?? [])
  const fields: SchemaField[] = []
  const unsupportedKeys: string[] = []

  for (const [key, prop] of Object.entries(s.properties)) {
    const resolved = resolvePrimitive(prop)
    if (!resolved) {
      unsupportedKeys.push(key)
      continue
    }
    fields.push({
      key,
      title: prop.title ?? key,
      description: prop.description,
      required: required.has(key),
      kind: resolved.kind,
      enumValues: resolved.enumValues,
      default: prop.default,
    })
  }

  return { fields, unsupportedKeys }
}

/** Seed a values object from each field's schema default (skips fields with no default). */
export function defaultValuesForSchema(parsed: ParsedSchema): Record<string, unknown> {
  const values: Record<string, unknown> = {}
  for (const field of parsed.fields) {
    if (field.default !== undefined && field.default !== null) {
      values[field.key] = field.default
    }
  }
  return values
}

/** True when every required field in the schema has a defined, non-empty value. */
export function schemaValuesComplete(parsed: ParsedSchema, values: Record<string, unknown>): boolean {
  return parsed.fields
    .filter((f) => f.required)
    .every((f) => values[f.key] !== undefined && values[f.key] !== null && values[f.key] !== '')
}
