// components/layout/StatusBar.tsx
'use client'

import { useState, useEffect } from 'react'
import { Activity, Zap, HardDrive, Clock, Server, Wifi } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { utils } from '@/lib/api'

interface SystemStatus {
  health: string
  llmConnected: boolean
  isLoading: boolean
  supportedFormats: string[]
  maxFileSize: number
}

interface StatusBarProps {
  systemStatus: SystemStatus
  sidebarCollapsed: boolean // NEW: Track sidebar state
}

export function StatusBar({ systemStatus, sidebarCollapsed }: StatusBarProps) {
  const [currentTime, setCurrentTime] = useState<Date | null>(null)
  const [connectionCount, setConnectionCount] = useState(0)
  const [isClient, setIsClient] = useState(false)

  // Fix hydration issue by only showing time after client-side hydration
  useEffect(() => {
    setIsClient(true)
    setCurrentTime(new Date())
    
    // Update time every second only after hydration
    const timer = setInterval(() => {
      setCurrentTime(new Date())
    }, 1000)

    return () => clearInterval(timer)
  }, [])

  // Simulate connection counter (in real app, this would come from your backend)
  useEffect(() => {
    const interval = setInterval(() => {
      setConnectionCount(prev => Math.max(0, prev + Math.floor(Math.random() * 3) - 1))
    }, 5000)

    return () => clearInterval(interval)
  }, [])

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString([], { 
      hour: '2-digit', 
      minute: '2-digit',
      second: '2-digit'
    })
  }

  const getUptimeDisplay = () => {
    // In a real app, you'd track actual uptime
    if (!isClient) return '0h 0m' // Prevent hydration mismatch
    
    const uptime = Math.floor(Date.now() / 1000) % 86400 // Simulated daily reset
    const hours = Math.floor(uptime / 3600)
    const minutes = Math.floor((uptime % 3600) / 60)
    return `${hours}h ${minutes}m`
  }

  return (
    <div className={`bg-gray-50 border-t border-gray-200 px-4 py-2 flex items-center justify-between text-xs text-gray-600 transition-all duration-300 z-60 relative ${
      // Adjust margin based on sidebar state - only on desktop
      `lg:ml-${sidebarCollapsed ? '16' : '64'}`
    }`}>
      <div className="flex items-center space-x-6">
        {/* API Health Status */}
        <div className="flex items-center space-x-1">
          <Activity className="w-3 h-3" />
          <span>API:</span>
          <Badge 
            variant={systemStatus.health === 'healthy' ? 'success' : 'error'} 
            className="text-xs py-0 px-1"
          >
            {systemStatus.health}
          </Badge>
        </div>
        
        {/* LLM Connection Status */}
        <div className="flex items-center space-x-1">
          <Zap className="w-3 h-3" />
          <span>LLM:</span>
          <Badge 
            variant={systemStatus.llmConnected ? 'success' : 'error'} 
            className="text-xs py-0 px-1"
          >
            {systemStatus.llmConnected ? 'Connected' : 'Disconnected'}
          </Badge>
        </div>

        {/* Storage Info */}
        <div className="flex items-center space-x-1">
          <HardDrive className="w-3 h-3" />
          <span>Max Upload:</span>
          <span className="font-mono">{utils.formatFileSize(systemStatus.maxFileSize)}</span>
        </div>

        {/* Supported Formats */}
        <div className="hidden md:flex items-center space-x-1">
          <Server className="w-3 h-3" />
          <span>Formats:</span>
          <span className="font-mono">{systemStatus.supportedFormats.length} types</span>
        </div>

        {/* Active Connections (simulated) */}
        <div className="hidden lg:flex items-center space-x-1">
          <Wifi className="w-3 h-3" />
          <span>Connections:</span>
          <span className="font-mono">{connectionCount}</span>
        </div>
      </div>

      <div className="flex items-center space-x-6">
        {/* System Uptime */}
        <div className="hidden md:flex items-center space-x-1">
          <span>Uptime:</span>
          <span className="font-mono">{getUptimeDisplay()}</span>
        </div>
        
        {/* Current Time - Only show after hydration */}
        <div className="flex items-center space-x-1">
          <Clock className="w-3 h-3" />
          <span className="font-mono">
            {isClient && currentTime ? formatTime(currentTime) : '--:--:--'}
          </span>
        </div>
        
        {/* Version */}
        <div className="flex items-center space-x-1">
          <span className="text-gray-400">Curatore</span>
          <span className="font-mono text-gray-500">v2.0.0</span>
        </div>
      </div>
    </div>
  )
}