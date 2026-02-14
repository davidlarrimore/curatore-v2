'use client'

import { type FunctionParameter } from '@/lib/api'
import { TextInput } from './TextInput'
import { TextareaInput } from './TextareaInput'
import { NumberInput } from './NumberInput'
import { BooleanToggle } from './BooleanToggle'
import { EnumSelect } from './EnumSelect'
import { MultiEnumSelect } from './MultiEnumSelect'
import { ListInput } from './ListInput'
import { JsonInput } from './JsonInput'
import { EntityInput } from './EntityInput'
import { DateInput } from './DateInput'

interface FunctionInputProps {
  param: FunctionParameter
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  value: any
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onChange: (value: any) => void
  disabled?: boolean
}

// Parameters that should use textarea for long text
const TEXTAREA_PARAMS = ['prompt', 'system_prompt', 'text', 'content', 'instructions', 'template', 'message', 'body']

// Parameters that should use entity pickers
const ENTITY_PATTERNS: Record<string, string> = {
  'asset_id': 'asset',
  'asset_ids': 'asset',
  'solicitation_id': 'solicitation',
  'collection_id': 'collection',
}

// Date parameter name patterns
const DATE_PARAM_PATTERNS = [
  '_date',      // ends with _date
  '_after',     // ends with _after (e.g., response_deadline_after)
  '_before',    // ends with _before
  'deadline',   // contains deadline
  'start_at',   // timestamp patterns
  'end_at',
  'created_at',
  'updated_at',
]

/**
 * Check if a parameter should use a date input.
 */
function isDateParam(param: FunctionParameter): boolean {
  const name = param.name.toLowerCase()

  // Check if description mentions date format
  const desc = (param.description || '').toLowerCase()
  if (desc.includes('yyyy-mm-dd') || desc.includes('date format')) {
    return true
  }

  // Check parameter name patterns
  return DATE_PARAM_PATTERNS.some(pattern => name.includes(pattern))
}

/**
 * Router component that selects the appropriate input type based on parameter metadata.
 */
export function FunctionInput({ param, value, onChange, disabled }: FunctionInputProps) {
  // Priority 1: Check for entity picker params
  for (const [pattern, entityType] of Object.entries(ENTITY_PATTERNS)) {
    if (param.name === pattern || param.name.endsWith(`_${pattern}`)) {
      return (
        <EntityInput
          param={param}
          entityType={entityType}
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
      )
    }
  }

  // Priority 2: Date parameters
  if (isDateParam(param) && param.type === 'str') {
    return (
      <DateInput
        param={param}
        value={value ?? ''}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Priority 3: List types with enum_values -> MultiEnumSelect (checkboxes)
  const isListType = param.type.startsWith('list[') || param.type === 'list' || param.type === 'List[str]'
  if (isListType && param.enum_values && param.enum_values.length > 0) {
    return (
      <MultiEnumSelect
        param={param}
        value={value ?? []}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Priority 4: Single value with enum_values -> EnumSelect
  if (param.enum_values && param.enum_values.length > 0) {
    return (
      <EnumSelect
        param={param}
        value={value ?? ''}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Priority 5: List types without enum_values
  if (isListType) {
    return (
      <ListInput
        param={param}
        value={value ?? []}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Priority 6: Dict/object types
  if (param.type === 'dict' || param.type.startsWith('Dict[') || param.type === 'object' || param.type.startsWith('Optional[Dict')) {
    return (
      <JsonInput
        param={param}
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Priority 7: Boolean type
  if (param.type === 'bool' || param.type === 'boolean') {
    return (
      <BooleanToggle
        param={param}
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Priority 8: Number types
  if (param.type === 'int' || param.type === 'float' || param.type === 'number') {
    return (
      <NumberInput
        param={param}
        value={value ?? ''}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Priority 9: Long text params that should use textarea
  if (TEXTAREA_PARAMS.some(p => param.name.toLowerCase().includes(p))) {
    return (
      <TextareaInput
        param={param}
        value={value ?? ''}
        onChange={onChange}
        disabled={disabled}
      />
    )
  }

  // Default: TextInput
  return (
    <TextInput
      param={param}
      value={value ?? ''}
      onChange={onChange}
      disabled={disabled}
    />
  )
}

export default FunctionInput
