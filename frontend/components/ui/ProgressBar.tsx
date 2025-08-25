// components/ui/ProgressBar.tsx
'use client'

import React from 'react'
import { CheckCircle2, LucideIcon } from 'lucide-react'

export interface ProgressStep {
  id: string
  name: string
  subtitle?: string
  icon: LucideIcon
}

export type StepStatus = 'completed' | 'current' | 'pending'

export interface ProgressBarProps {
  steps: ProgressStep[]
  currentStep: string
  onStepChange?: (stepId: string) => void
  getStepStatus: (stepId: string) => StepStatus
  getStepClickable?: (stepId: string) => boolean
  className?: string
  variant?: 'default' | 'slim'
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  steps,
  currentStep,
  onStepChange,
  getStepStatus,
  getStepClickable = () => true,
  className = '',
  variant = 'default'
}) => {
  const isSlim = variant === 'slim'
  
  return (
    <div className={`bg-gradient-to-r from-slate-50 to-slate-100 border-b border-slate-200 ${className}`}>
      <div className={`${isSlim ? 'px-6 py-2' : 'px-6 py-4'}`}>
        <nav aria-label="Progress" className="w-full">
          <div className="flex items-center justify-center">
            {steps.map((step, stepIdx) => {
              const status = getStepStatus(step.id)
              const isCompleted = status === 'completed'
              const isCurrent = status === 'current'
              const isClickable = getStepClickable(step.id)

              const IconComponent = step.icon

              return (
                <div key={step.id} className="flex items-center group relative">
                  {/* Step Container */}
                  <div className="relative">
                    <button
                      onClick={() => {
                        if (isClickable && onStepChange) {
                          onStepChange(step.id)
                        }
                      }}
                      disabled={!isClickable}
                      className={`
                        relative flex items-center transition-all duration-300 transform
                        ${stepIdx === 0 ? 'rounded-l-xl' : ''}
                        ${stepIdx === steps.length - 1 ? 'rounded-r-xl' : ''}
                        ${isSlim ? 'px-6 py-3' : 'px-8 py-4'}
                        ${stepIdx === 0 ? (isSlim ? 'pl-4' : 'pl-6') : ''}
                        ${stepIdx === steps.length - 1 ? (isSlim ? 'pr-4' : 'pr-6') : (isSlim ? 'pr-8' : 'pr-12')}
                        ${isClickable ? 'cursor-pointer hover:scale-[1.01]' : 'cursor-default'}
                        ${isCurrent 
                          ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow-lg z-30 scale-[1.01]' 
                          : isCompleted
                            ? 'bg-gradient-to-r from-emerald-500 to-emerald-600 text-white shadow-md z-20'
                            : isClickable
                              ? 'bg-white text-slate-600 shadow-sm hover:shadow-md border border-slate-200 z-10'
                              : 'bg-slate-100 text-slate-400 border border-slate-200 z-10'
                        }
                      `}
                    >
                      {/* Chevron decoration */}
                      {stepIdx < steps.length - 1 && (
                        <div className={`
                          absolute right-0 top-1/2 transform -translate-y-1/2 translate-x-1/2 
                          w-0 h-0 border-y-transparent z-40
                          ${isSlim ? 'border-l-[12px] border-y-[18px]' : 'border-l-[16px] border-y-[24px]'}
                          ${isCurrent 
                            ? 'border-l-blue-700' 
                            : isCompleted
                              ? 'border-l-emerald-600'
                              : isClickable
                                ? 'border-l-white'
                                : 'border-l-slate-100'
                          }
                        `} />
                      )}

                      {/* Content */}
                      <div className="flex items-center space-x-3">
                        {/* Icon with status indicator */}
                        <div className="relative flex-shrink-0">
                          <div className={`
                            rounded-full flex items-center justify-center transition-all duration-300
                            ${isSlim ? 'w-5 h-5' : 'w-6 h-6'}
                            ${isCompleted 
                              ? 'bg-white text-emerald-600' 
                              : isCurrent
                                ? 'bg-white text-blue-600'
                                : 'opacity-80'
                            }
                          `}>
                            {isCompleted ? (
                              <CheckCircle2 className={isSlim ? 'w-3.5 h-3.5' : 'w-4 h-4'} />
                            ) : (
                              <IconComponent className={isSlim ? 'w-3.5 h-3.5' : 'w-4 h-4'} />
                            )}
                          </div>
                          
                          {/* Processing pulse indicator */}
                          {isCurrent && (
                            <div className="absolute -inset-1">
                              <div className={`border-2 border-white border-opacity-40 rounded-full animate-pulse ${
                                isSlim ? 'w-7 h-7' : 'w-8 h-8'
                              }`}></div>
                            </div>
                          )}
                        </div>

                        {/* Stage info */}
                        <div className="flex-1 text-left min-w-0">
                          <div className={`font-semibold truncate ${isSlim ? 'text-sm' : 'text-base'}`}>
                            {step.name}
                          </div>
                          {!isSlim && step.subtitle && (
                            <div className={`text-xs truncate mt-0.5 opacity-90`}>
                              {step.subtitle}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Enhanced hover shadow */}
                      {isClickable && (
                        <div className={`
                          absolute inset-0 rounded-xl transition-all duration-300 pointer-events-none
                          ${!isCurrent && !isCompleted ? 'group-hover:shadow-lg group-hover:-translate-y-0.5' : ''}
                        `} />
                      )}
                    </button>
                  </div>

                  {/* Connection line */}
                  {stepIdx < steps.length - 1 && (
                    <div className={`
                      h-0.5 transition-colors duration-500 -mx-1 z-10
                      ${isSlim ? 'w-8' : 'w-12'}
                      ${isCompleted && getStepStatus(steps[stepIdx + 1].id) !== 'pending'
                        ? 'bg-gradient-to-r from-emerald-400 to-blue-400' 
                        : 'bg-slate-300'
                      }
                    `} />
                  )}
                </div>
              )
            })}
          </div>
        </nav>
      </div>
    </div>
  )
}

// Export default for easier importing
export default ProgressBar

// Helper hook for common progress bar logic
export const useProgressBar = (
  steps: string[],
  currentStep: string,
  completedSteps: string[] = []
) => {
  const getStepStatus = (stepId: string): StepStatus => {
    if (completedSteps.includes(stepId)) return 'completed'
    if (stepId === currentStep) return 'current'
    return 'pending'
  }

  const getStepIndex = (stepId: string) => steps.indexOf(stepId)
  const getCurrentStepIndex = () => getStepIndex(currentStep)
  
  const canNavigateToStep = (stepId: string) => {
    const stepIndex = getStepIndex(stepId)
    const currentIndex = getCurrentStepIndex()
    // Can always go back, can only go forward if previous steps are completed
    return stepIndex <= currentIndex || completedSteps.includes(steps[stepIndex - 1])
  }

  const getNextStep = () => {
    const currentIndex = getCurrentStepIndex()
    return currentIndex < steps.length - 1 ? steps[currentIndex + 1] : null
  }

  const getPreviousStep = () => {
    const currentIndex = getCurrentStepIndex()
    return currentIndex > 0 ? steps[currentIndex - 1] : null
  }

  return {
    getStepStatus,
    getStepIndex,
    getCurrentStepIndex,
    canNavigateToStep,
    getNextStep,
    getPreviousStep
  }
}