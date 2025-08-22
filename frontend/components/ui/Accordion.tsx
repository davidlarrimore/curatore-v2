// components/ui/Accordion.tsx
'use client'

import { useState, ReactNode } from 'react';

interface AccordionItemProps {
  id: string;
  title: string;
  subtitle?: string;
  icon?: string;
  children: ReactNode;
  isOpen: boolean;
  onToggle: (id: string) => void;
  disabled?: boolean;
  completed?: boolean;
}

export function AccordionItem({ 
  id, 
  title, 
  subtitle, 
  icon, 
  children, 
  isOpen, 
  onToggle, 
  disabled = false,
  completed = false 
}: AccordionItemProps) {
  const handleToggle = () => {
    if (!disabled) {
      onToggle(id);
    }
  };

  return (
    <div className={`border rounded-lg ${disabled ? 'opacity-50' : ''}`}>
      <button
        type="button"
        onClick={handleToggle}
        disabled={disabled}
        className={`w-full px-6 py-4 text-left flex items-center justify-between transition-colors ${
          disabled 
            ? 'cursor-not-allowed bg-gray-50' 
            : isOpen 
              ? 'bg-blue-50 hover:bg-blue-100' 
              : 'bg-white hover:bg-gray-50'
        }`}
      >
        <div className="flex items-center space-x-3">
          {icon && <span className="text-2xl">{icon}</span>}
          <div>
            <h3 className={`text-lg font-semibold ${
              disabled ? 'text-gray-400' : 'text-gray-900'
            }`}>
              {title}
              {completed && <span className="ml-2 text-green-600">✓</span>}
            </h3>
            {subtitle && (
              <p className={`text-sm ${
                disabled ? 'text-gray-400' : 'text-gray-600'
              }`}>
                {subtitle}
              </p>
            )}
          </div>
        </div>
        
        <div className="flex items-center space-x-2">
          {completed && (
            <span className="px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full">
              Complete
            </span>
          )}
          <svg
            className={`w-5 h-5 transition-transform ${
              isOpen ? 'rotate-180' : ''
            } ${disabled ? 'text-gray-400' : 'text-gray-600'}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>
      
      {isOpen && (
        <div className="px-6 py-4 border-t bg-white">
          {children}
        </div>
      )}
    </div>
  );
}

interface AccordionProps {
  activeId: string;
  onActiveChange: (id: string) => void;
  children: ReactNode;
}

export function Accordion({ activeId, onActiveChange, children }: AccordionProps) {
  return (
    <div className="space-y-2">
      {children}
    </div>
  );
}