import * as yaml from 'js-yaml'

/**
 * Generate YAML output for a function call.
 * Used to show users how to use the function in procedures/pipelines.
 */
export function generateFunctionYaml(
  functionName: string,
  params: Record<string, any>,
  stepName?: string
): string {
  // Filter out undefined, null, and empty string values
  const cleanParams = Object.fromEntries(
    Object.entries(params).filter(([_, v]) => {
      if (v === undefined || v === null) return false
      if (v === '') return false
      if (Array.isArray(v) && v.length === 0) return false
      return true
    })
  )

  const step: Record<string, any> = {
    name: stepName || functionName.replace(/_/g, '-'),
    function: functionName,
  }

  // Only add params if there are any
  if (Object.keys(cleanParams).length > 0) {
    step.params = cleanParams
  }

  return yaml.dump(step, {
    indent: 2,
    lineWidth: -1, // Don't wrap lines
    quotingType: '"',
    forceQuotes: false,
  })
}

/**
 * Generate a full procedure YAML example.
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
      const cleanParams = step.params
        ? Object.fromEntries(
            Object.entries(step.params).filter(([_, v]) => {
              if (v === undefined || v === null) return false
              if (v === '') return false
              if (Array.isArray(v) && v.length === 0) return false
              return true
            })
          )
        : undefined

      return {
        name: step.name,
        function: step.function,
        ...(cleanParams && Object.keys(cleanParams).length > 0 && { params: cleanParams }),
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
