/**
 * Job Type Configuration
 *
 * Centralized configuration for all job types tracked by the Running Job Panel.
 * Provides icons, colors, labels, and notification messages for each job type.
 */

import {
  Search,
  FolderSync,
  Globe,
  Upload,
  Workflow,
  Zap,
  LucideIcon,
} from 'lucide-react'

// Job type identifiers
export type JobType =
  | 'sam_pull'
  | 'sharepoint_sync'
  | 'scrape'
  | 'upload'
  | 'pipeline'
  | 'procedure'

// Configuration for a single job type
export interface JobTypeConfig {
  label: string
  icon: LucideIcon
  color: 'purple' | 'blue' | 'emerald' | 'indigo' | 'amber' | 'cyan'
  resourceType: string
  hasChildJobs: boolean
  phases: string[]
  completedToast: (displayName: string) => string
  failedToast: (displayName: string, error?: string) => string
}

// Job type configurations
export const JOB_TYPE_CONFIG: Record<JobType, JobTypeConfig> = {
  sam_pull: {
    label: 'SAM.gov Pull',
    icon: Search,
    color: 'purple',
    resourceType: 'sam_search',
    hasChildJobs: true,
    phases: ['fetching', 'downloading', 'extracting'],
    completedToast: (name) => `SAM pull completed: ${name}`,
    failedToast: (name, error) => `SAM pull failed: ${name}${error ? ` - ${error}` : ''}`,
  },
  sharepoint_sync: {
    label: 'SharePoint Sync',
    icon: FolderSync,
    color: 'blue',
    resourceType: 'sharepoint_config',
    hasChildJobs: true,
    phases: ['scanning', 'syncing', 'extracting', 'detecting_deletions'],
    completedToast: (name) => `SharePoint sync completed: ${name}`,
    failedToast: (name, error) => `SharePoint sync failed: ${name}${error ? ` - ${error}` : ''}`,
  },
  scrape: {
    label: 'Web Scrape',
    icon: Globe,
    color: 'emerald',
    resourceType: 'scrape_collection',
    hasChildJobs: true,
    phases: ['crawling', 'extracting'],
    completedToast: (name) => `Web scrape completed: ${name}`,
    failedToast: (name, error) => `Web scrape failed: ${name}${error ? ` - ${error}` : ''}`,
  },
  upload: {
    label: 'File Upload',
    icon: Upload,
    color: 'indigo',
    resourceType: 'upload_batch',
    hasChildJobs: true,
    phases: ['uploading', 'extracting'],
    completedToast: (name) => `Upload completed: ${name}`,
    failedToast: (name, error) => `Upload failed: ${name}${error ? ` - ${error}` : ''}`,
  },
  pipeline: {
    label: 'Pipeline',
    icon: Workflow,
    color: 'amber',
    resourceType: 'pipeline',
    hasChildJobs: false,
    phases: [], // Dynamic based on pipeline definition
    completedToast: (name) => `Pipeline completed: ${name}`,
    failedToast: (name, error) => `Pipeline failed: ${name}${error ? ` - ${error}` : ''}`,
  },
  procedure: {
    label: 'Procedure',
    icon: Zap,
    color: 'cyan',
    resourceType: 'procedure',
    hasChildJobs: false,
    phases: [],
    completedToast: (name) => `Procedure completed: ${name}`,
    failedToast: (name, error) => `Procedure failed: ${name}${error ? ` - ${error}` : ''}`,
  },
}

// Get job type from run_type string
export function getJobTypeFromRunType(runType: string): JobType | null {
  // Direct mappings
  const directMap: Record<string, JobType> = {
    sam_pull: 'sam_pull',
    sharepoint_sync: 'sharepoint_sync',
    scrape: 'scrape',
    upload: 'upload',
    pipeline: 'pipeline',
    procedure: 'procedure',
  }

  if (directMap[runType]) {
    return directMap[runType]
  }

  // Check aliases
  if (runType === 'gdrive_sync') return 'sharepoint_sync' // Future compatibility
  if (runType.startsWith('sam_')) return 'sam_pull'
  if (runType.startsWith('scrape_')) return 'scrape'
  if (runType.startsWith('sharepoint_')) return 'sharepoint_sync'

  return null
}

// Get Tailwind color classes for a job type
export function getJobTypeColorClasses(jobType: JobType): {
  bg: string
  bgLight: string
  text: string
  border: string
} {
  const config = JOB_TYPE_CONFIG[jobType]
  const color = config.color

  return {
    bg: `bg-${color}-500`,
    bgLight: `bg-${color}-50 dark:bg-${color}-900/20`,
    text: `text-${color}-600 dark:text-${color}-400`,
    border: `border-${color}-200 dark:border-${color}-800`,
  }
}
