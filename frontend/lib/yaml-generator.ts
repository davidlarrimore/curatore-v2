import * as yaml from 'js-yaml'

/**
 * Clean parameters by removing undefined, null, empty string, and empty array values.
 */
function cleanParams(params: Record<string, any>): Record<string, any> {
  return Object.fromEntries(
    Object.entries(params).filter(([_, v]) => {
      if (v === undefined || v === null) return false
      if (v === '') return false
      if (Array.isArray(v) && v.length === 0) return false
      return true
    })
  )
}

/**
 * Generate JSON output for a function step.
 * Used to show users how to use the function in procedure definitions.
 */
export function generateFunctionJson(
  functionName: string,
  params: Record<string, any>,
  stepName?: string
): string {
  const cleaned = cleanParams(params)

  const step: Record<string, any> = {
    name: stepName || functionName.replace(/_/g, '-'),
    function: functionName,
  }

  if (Object.keys(cleaned).length > 0) {
    step.params = cleaned
  }

  return JSON.stringify(step, null, 2)
}

/**
 * Generate a full procedure JSON example.
 */
export function generateProcedureJson(
  name: string,
  description: string,
  steps: Array<{ name: string; function: string; params?: Record<string, any> }>
): string {
  const procedure = {
    name,
    description,
    steps: steps.map((step) => {
      const cleaned = step.params ? cleanParams(step.params) : undefined
      return {
        name: step.name,
        function: step.function,
        ...(cleaned && Object.keys(cleaned).length > 0 && { params: cleaned }),
      }
    }),
  }

  return JSON.stringify(procedure, null, 2)
}

// Legacy YAML exports (used by procedure editor pages)

/**
 * Generate YAML output for a function call.
 * @deprecated Use generateFunctionJson instead - procedures now use JSON definitions.
 */
export function generateFunctionYaml(
  functionName: string,
  params: Record<string, any>,
  stepName?: string
): string {
  const cleaned = cleanParams(params)

  const step: Record<string, any> = {
    name: stepName || functionName.replace(/_/g, '-'),
    function: functionName,
  }

  if (Object.keys(cleaned).length > 0) {
    step.params = cleaned
  }

  return yaml.dump(step, {
    indent: 2,
    lineWidth: -1,
    quotingType: '"',
    forceQuotes: false,
  })
}

/**
 * Generate a full procedure YAML example.
 * @deprecated Use generateProcedureJson instead - procedures now use JSON definitions.
 */
export function generateProcedureYaml(
  name: string,
  description: string,
  steps: Array<{ name: string; function: string; params?: Record<string, any> }>
): string {
  const procedure = {
    name,
    description,
    steps: steps.map((step) => {
      const cleaned = step.params ? cleanParams(step.params) : undefined
      return {
        name: step.name,
        function: step.function,
        ...(cleaned && Object.keys(cleaned).length > 0 && { params: cleaned }),
      }
    }),
  }

  return yaml.dump(procedure, {
    indent: 2,
    lineWidth: -1,
    quotingType: '"',
    forceQuotes: false,
  })
}
