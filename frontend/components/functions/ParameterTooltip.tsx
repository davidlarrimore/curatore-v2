'use client'

import { type FunctionParameter } from '@/lib/api'
import { InfoTooltip, TooltipSection, TooltipCode } from '@/components/ui/InfoTooltip'

interface ParameterTooltipProps {
  param: FunctionParameter
  position?: 'top' | 'bottom' | 'left' | 'right'
}

/**
 * Parse enum option which may be in "value|label" format or just "value".
 * Returns { value, label } where label defaults to value if not specified.
 */
function parseEnumOption(option: string): { value: string; label: string } {
  const pipeIndex = option.indexOf('|')
  if (pipeIndex > -1) {
    return {
      value: option.substring(0, pipeIndex),
      label: option.substring(pipeIndex + 1),
    }
  }
  return { value: option, label: option }
}

/**
 * Tooltip that shows detailed information about a function parameter.
 * Displays description, type, default value, example, and enum options.
 */
export function ParameterTooltip({ param, position = 'right' }: ParameterTooltipProps) {
  const hasContent =
    param.description ||
    param.default !== undefined ||
    param.example !== undefined ||
    (param.enum_values && param.enum_values.length > 0)

  // Don't show tooltip if there's no useful content
  if (!hasContent) {
    return null
  }

  // Parse enum options for display
  const enumOptions = param.enum_values?.map(parseEnumOption) || []

  return (
    <InfoTooltip position={position}>
      <div className="space-y-2.5">
        {/* Description */}
        {param.description && (
          <TooltipSection label="Description">
            <p className="text-sm leading-relaxed">{param.description}</p>
          </TooltipSection>
        )}

        {/* Type */}
        <TooltipSection label="Type">
          <TooltipCode>{param.type}</TooltipCode>
          {param.required ? (
            <span className="ml-2 text-xs text-red-400">Required</span>
          ) : (
            <span className="ml-2 text-xs text-gray-500">Optional</span>
          )}
        </TooltipSection>

        {/* Default Value */}
        {param.default !== undefined && (
          <TooltipSection label="Default">
            <TooltipCode>
              {typeof param.default === 'object'
                ? JSON.stringify(param.default)
                : String(param.default)}
            </TooltipCode>
          </TooltipSection>
        )}

        {/* Example */}
        {param.example !== undefined && (
          <TooltipSection label="Example">
            <TooltipCode>
              {typeof param.example === 'object'
                ? JSON.stringify(param.example, null, 2)
                : String(param.example)}
            </TooltipCode>
          </TooltipSection>
        )}

        {/* Enum Options */}
        {enumOptions.length > 0 && (
          <TooltipSection label="Options">
            <div className="flex flex-wrap gap-1 mt-1">
              {enumOptions.map((option) => (
                <span
                  key={option.value}
                  className="inline-flex px-1.5 py-0.5 rounded bg-indigo-900/50 text-indigo-300 text-xs"
                >
                  <span className="font-mono">{option.value}</span>
                  {option.label !== option.value && (
                    <span className="ml-1 text-indigo-400">= {option.label}</span>
                  )}
                </span>
              ))}
            </div>
          </TooltipSection>
        )}
      </div>
    </InfoTooltip>
  )
}
