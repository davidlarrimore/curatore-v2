'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  FileText,
  Building2,
  Globe,
  FolderSync,
  Wrench,
  Activity,
  ChevronDown,
  ChevronRight,
  Info,
  AlertCircle,
  Copy,
  Check,
  Calendar,
  Timer,
  Hash,
  Settings,
  BarChart3,
  ListTree,
  ScrollText,
  ExternalLink,
  Play,
  Pause,
  StopCircle,
  Zap,
  Sparkles,
  Database,
} from 'lucide-react';
import { runsApi, queueAdminApi, assetsApi } from '@/lib/api';
import type {
  Run,
  RunLogEvent,
  QueueDefinition,
  Asset,
} from '@/lib/api';
import { formatTimeAgo, formatDateTime, formatDuration, formatShortDateTime } from '@/lib/date-utils';

// Status configuration
const STATUS_CONFIG: Record<string, { color: string; bgColor: string; icon: React.ElementType; label: string }> = {
  pending: { color: 'text-gray-600 dark:text-gray-400', bgColor: 'bg-gray-100 dark:bg-gray-800', icon: Clock, label: 'Pending' },
  submitted: { color: 'text-blue-600 dark:text-blue-400', bgColor: 'bg-blue-100 dark:bg-blue-900/30', icon: Loader2, label: 'Submitted' },
  running: { color: 'text-indigo-600 dark:text-indigo-400', bgColor: 'bg-indigo-100 dark:bg-indigo-900/30', icon: Loader2, label: 'Running' },
  completed: { color: 'text-emerald-600 dark:text-emerald-400', bgColor: 'bg-emerald-100 dark:bg-emerald-900/30', icon: CheckCircle2, label: 'Completed' },
  failed: { color: 'text-red-600 dark:text-red-400', bgColor: 'bg-red-100 dark:bg-red-900/30', icon: XCircle, label: 'Failed' },
  timed_out: { color: 'text-amber-600 dark:text-amber-400', bgColor: 'bg-amber-100 dark:bg-amber-900/30', icon: AlertTriangle, label: 'Timed Out' },
  cancelled: { color: 'text-gray-600 dark:text-gray-400', bgColor: 'bg-gray-100 dark:bg-gray-800', icon: StopCircle, label: 'Cancelled' },
};

// Job type configuration
const JOB_TYPE_CONFIG: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  extraction: { icon: FileText, label: 'Extraction', color: 'text-blue-600 dark:text-blue-400' },
  sam_pull: { icon: Building2, label: 'SAM.gov Pull', color: 'text-amber-600 dark:text-amber-400' },
  scrape: { icon: Globe, label: 'Web Scrape', color: 'text-emerald-600 dark:text-emerald-400' },
  sharepoint_sync: { icon: FolderSync, label: 'SharePoint Sync', color: 'text-purple-600 dark:text-purple-400' },
  system_maintenance: { icon: Wrench, label: 'Maintenance', color: 'text-gray-600 dark:text-gray-400' },
  salesforce_import: { icon: Database, label: 'Salesforce Import', color: 'text-cyan-600 dark:text-cyan-400' },
};

// Log level configuration
const LOG_LEVEL_CONFIG: Record<string, { color: string; bgColor: string; icon: React.ElementType }> = {
  INFO: { color: 'text-blue-600 dark:text-blue-400', bgColor: 'bg-blue-50 dark:bg-blue-900/20', icon: Info },
  WARN: { color: 'text-amber-600 dark:text-amber-400', bgColor: 'bg-amber-50 dark:bg-amber-900/20', icon: AlertTriangle },
  ERROR: { color: 'text-red-600 dark:text-red-400', bgColor: 'bg-red-50 dark:bg-red-900/20', icon: AlertCircle },
};

interface JobDetailData {
  run: Run;
  logs: RunLogEvent[];
  queueDefinition?: QueueDefinition;
  assets?: Asset[];
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
      title={`Copy ${label || 'to clipboard'}`}
    >
      {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

function JsonViewer({ data, title, defaultExpanded = false }: { data: unknown; title: string; defaultExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (!data || (typeof data === 'object' && Object.keys(data as object).length === 0)) {
    return null;
  }

  const jsonString = JSON.stringify(data, null, 2);

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-800/50">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 font-medium text-gray-900 dark:text-white hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
        >
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <span>{title}</span>
        </button>
        <CopyButton text={jsonString} label={title} />
      </div>
      {expanded && (
        <pre className="p-4 text-sm overflow-x-auto bg-gray-900 text-gray-100 dark:bg-gray-950">
          <code>{jsonString}</code>
        </pre>
      )}
    </div>
  );
}

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.runId as string;

  const [data, setData] = useState<JobDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [cancelling, setCancelling] = useState(false);
  const [forceKilling, setForceKilling] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const fetchData = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) setRefreshing(true);

    try {
      // Fetch run with logs
      const runWithLogs = await runsApi.getRunWithLogs(runId);

      // Fetch queue registry for capabilities
      const registry = await queueAdminApi.getRegistry();
      const queueDef = registry.queues[runWithLogs.run.run_type] ||
                       registry.queues[registry.run_type_mapping[runWithLogs.run.run_type]];

      // Fetch associated assets if extraction
      let assets: Asset[] = [];
      if (runWithLogs.run.run_type === 'extraction' && runWithLogs.run.input_asset_ids?.length) {
        try {
          const assetPromises = runWithLogs.run.input_asset_ids.map(id =>
            assetsApi.getAsset(undefined, id).catch(() => null)
          );
          const assetResults = await Promise.all(assetPromises);
          assets = assetResults.filter((a): a is Asset => a !== null);
        } catch (e) {
          console.warn('Failed to fetch assets:', e);
        }
      }

      setData({
        run: runWithLogs.run,
        logs: runWithLogs.logs || [],
        queueDefinition: queueDef,
        assets,
      });
      setError(null);
    } catch (err) {
      console.error('Failed to fetch job details:', err);
      setError(err instanceof Error ? err.message : 'Failed to load job details');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [runId]);

  // Initial fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh for active jobs
  useEffect(() => {
    if (!autoRefresh || !data) return;

    const isActive = ['pending', 'submitted', 'running'].includes(data.run.status);
    if (!isActive) return;

    const interval = setInterval(() => fetchData(false), 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, data, fetchData]);

  // Handle job cancellation
  const handleCancel = async () => {
    if (!data?.queueDefinition?.can_cancel) return;
    if (!confirm('Are you sure you want to cancel this job?')) return;

    setCancelling(true);
    setError(null);
    setSuccessMessage(null);

    try {
      await queueAdminApi.cancelJob(undefined, runId);
      setSuccessMessage('Job cancelled successfully');
      // Refresh data to show updated status
      await fetchData(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel job');
    } finally {
      setCancelling(false);
    }
  };

  // Handle force kill for stuck jobs
  const handleForceKill = async () => {
    if (!confirm(
      'Force Kill will terminate database connections and revoke the Celery task.\n\n' +
      'This is a destructive action that should only be used for stuck jobs.\n\n' +
      'Are you sure you want to force-kill this job?'
    )) return;

    setForceKilling(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const result = await queueAdminApi.forceKillJob(undefined, runId);
      setSuccessMessage(result.message);
      // Refresh data to show updated status
      await fetchData(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to force-kill job');
    } finally {
      setForceKilling(false);
    }
  };

  // Check if job appears stuck (running but no activity for 2+ minutes)
  const isJobStuck = useCallback(() => {
    if (!data?.run) return false;
    const { run } = data;
    if (!['running', 'submitted'].includes(run.status)) return false;
    if (!run.last_activity_at) return true; // No activity ever
    const lastActivity = new Date(run.last_activity_at).getTime();
    const now = Date.now();
    const inactiveMinutes = (now - lastActivity) / 60000;
    return inactiveMinutes >= 2;
  }, [data]);

  // Clear success message after a delay
  useEffect(() => {
    if (successMessage) {
      const timeout = setTimeout(() => setSuccessMessage(null), 3000);
      return () => clearTimeout(timeout);
    }
  }, [successMessage]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="flex items-center gap-3 text-gray-600 dark:text-gray-400">
          <Loader2 className="h-6 w-6 animate-spin" />
          <span>Loading job details...</span>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <XCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Failed to load job</h2>
          <p className="text-gray-600 dark:text-gray-400 mb-4">{error}</p>
          <button
            onClick={() => router.back()}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }

  const { run, logs, queueDefinition, assets } = data;
  const statusConfig = STATUS_CONFIG[run.status] || STATUS_CONFIG.pending;
  const jobTypeConfig = JOB_TYPE_CONFIG[run.run_type] || { icon: Activity, label: run.run_type, color: 'text-gray-600' };
  const StatusIcon = statusConfig.icon;
  const JobTypeIcon = jobTypeConfig.icon;
  const isActive = ['pending', 'submitted', 'running'].includes(run.status);

  // Get specific job label for maintenance jobs
  const getJobLabel = () => {
    if (run.run_type === 'system_maintenance' && run.config) {
      const taskName = run.config.scheduled_task_name || run.config.task_name;
      if (taskName) {
        // Map task names to human-readable labels
        const taskLabels: Record<string, string> = {
          'queue_pending_assets': 'Queue Pending Extractions',
          'cleanup_temp_files': 'Cleanup Temp Files',
          'cleanup_expired_jobs': 'Cleanup Expired Jobs',
          'detect_orphaned_objects': 'Detect Orphaned Objects',
          'enforce_retention': 'Enforce Retention Policies',
          'system_health_report': 'System Health Report',
          'search_reindex': 'Search Index Rebuild',
          'stale_run_cleanup': 'Stale Run Cleanup',
          'reindex_search': 'Reindex Search',
          'sharepoint_sync_hourly': 'SharePoint Sync (Hourly)',
          'sharepoint_sync_daily': 'SharePoint Sync (Daily)',
          'sam_pull_hourly': 'SAM.gov Pull (Hourly)',
          'sam_pull_daily': 'SAM.gov Pull (Daily)',
          'sync_sharepoint': 'SharePoint Sync',
          'sam_scheduled_pull': 'SAM.gov Scheduled Pull',
          'cleanup_old_runs': 'Cleanup Old Runs',
          'vacuum_database': 'Vacuum Database',
          'refresh_materialized_views': 'Refresh Views',
          'check_stale_extractions': 'Check Stale Extractions',
          'expire_old_tokens': 'Expire Old Tokens',
        };
        return taskLabels[taskName] || taskName.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase());
      }
    }
    return jobTypeConfig.label;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-4 mb-4">
            <Link
              href="/admin/queue"
              className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5 text-gray-600 dark:text-gray-400" />
            </Link>
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg ${statusConfig.bgColor}`}>
                  <JobTypeIcon className={`h-6 w-6 ${jobTypeConfig.color}`} />
                </div>
                <div>
                  <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                    {getJobLabel()} Job
                  </h1>
                  <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                    <span className="font-mono">{run.id}</span>
                    <CopyButton text={run.id} label="Run ID" />
                  </div>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {/* Cancel Button - only for active jobs with can_cancel capability */}
              {isActive && queueDefinition?.can_cancel && (
                <button
                  onClick={handleCancel}
                  disabled={cancelling}
                  className="px-4 py-2 rounded-lg border border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/50 transition-colors disabled:opacity-50 flex items-center gap-2"
                  title="Cancel this job"
                >
                  {cancelling ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <StopCircle className="h-4 w-4" />
                  )}
                  <span>Cancel</span>
                </button>
              )}
              {/* Force Kill Button - for stuck jobs */}
              {isActive && isJobStuck() && (
                <button
                  onClick={handleForceKill}
                  disabled={forceKilling}
                  className="px-4 py-2 rounded-lg border border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 hover:bg-orange-100 dark:hover:bg-orange-900/50 transition-colors disabled:opacity-50 flex items-center gap-2"
                  title="Force-terminate stuck database connections and Celery task"
                >
                  {forceKilling ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Zap className="h-4 w-4" />
                  )}
                  <span>Force Kill</span>
                </button>
              )}
              {isActive && (
                <button
                  onClick={() => setAutoRefresh(!autoRefresh)}
                  className={`px-3 py-2 rounded-lg border transition-colors ${
                    autoRefresh
                      ? 'border-indigo-300 bg-indigo-50 text-indigo-700 dark:border-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
                      : 'border-gray-300 bg-white text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300'
                  }`}
                >
                  {autoRefresh ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </button>
              )}
              <button
                onClick={() => fetchData(true)}
                disabled={refreshing}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {/* Status Badge */}
          <div className="flex items-center gap-4">
            <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium ${statusConfig.bgColor} ${statusConfig.color}`}>
              <StatusIcon className={`h-4 w-4 ${run.status === 'running' || run.status === 'submitted' ? 'animate-spin' : ''}`} />
              {statusConfig.label}
            </span>
            <span className="text-sm text-gray-500 dark:text-gray-400">
              Created {formatShortDateTime(run.created_at)}
            </span>
            {run.started_at && (
              <span className="text-sm text-gray-500 dark:text-gray-400">
                Started {formatShortDateTime(run.started_at)}
              </span>
            )}
            {run.completed_at && (
              <span className="text-sm text-gray-500 dark:text-gray-400">
                Completed {formatShortDateTime(run.completed_at)}
              </span>
            )}
          </div>

          {/* Success/Error Messages for actions */}
          {successMessage && (
            <div className="mt-4 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-4">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
                <p className="text-emerald-700 dark:text-emerald-300 text-sm font-medium">{successMessage}</p>
              </div>
            </div>
          )}
          {error && !loading && (
            <div className="mt-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4">
              <div className="flex items-center gap-3">
                <XCircle className="h-5 w-5 text-red-600 dark:text-red-400 flex-shrink-0" />
                <p className="text-red-700 dark:text-red-300 text-sm font-medium">{error}</p>
              </div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Content - Left Column */}
          <div className="lg:col-span-2 space-y-6">
            {/* Error Message */}
            {run.error_message && (
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <XCircle className="h-5 w-5 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <h3 className="font-semibold text-red-800 dark:text-red-200">Error</h3>
                    <p className="text-red-700 dark:text-red-300 text-sm mt-1 whitespace-pre-wrap font-mono">
                      {run.error_message}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Progress Section */}
            {run.progress && Object.keys(run.progress).length > 0 && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-indigo-500" />
                  Progress
                </h2>
                <ProgressDisplay progress={run.progress} />
              </div>
            )}

            {/* Results Summary */}
            {run.results_summary && Object.keys(run.results_summary).length > 0 && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <ListTree className="h-5 w-5 text-emerald-500" />
                  Results Summary
                </h2>
                <ResultsSummaryDisplay summary={run.results_summary} />
              </div>
            )}

            {/* Log Events Timeline */}
            <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                <ScrollText className="h-5 w-5 text-blue-500" />
                Activity Log
                <span className="text-sm font-normal text-gray-500 dark:text-gray-400">
                  ({logs.length} events)
                </span>
              </h2>
              <LogTimeline logs={logs} runCreatedAt={run.created_at} />
            </div>
          </div>

          {/* Sidebar - Right Column */}
          <div className="space-y-6">
            {/* Timestamps Card */}
            <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                <Calendar className="h-4 w-4 text-gray-500" />
                Timestamps
              </h3>
              <dl className="space-y-3 text-sm">
                <div>
                  <dt className="text-gray-500 dark:text-gray-400">Created</dt>
                  <dd className="font-medium text-gray-900 dark:text-white">{formatDateTime(run.created_at)}</dd>
                </div>
                {run.started_at && (
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">Started</dt>
                    <dd className="font-medium text-gray-900 dark:text-white">{formatDateTime(run.started_at)}</dd>
                  </div>
                )}
                {run.completed_at && (
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">Completed</dt>
                    <dd className="font-medium text-gray-900 dark:text-white">{formatDateTime(run.completed_at)}</dd>
                  </div>
                )}
                {run.started_at && (
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">Duration</dt>
                    <dd className="font-medium text-gray-900 dark:text-white">
                      {formatDuration(run.started_at, run.completed_at)}
                      {isActive && <span className="text-gray-500"> (running)</span>}
                    </dd>
                  </div>
                )}
                {isActive && (
                  <div className="pt-2 border-t border-gray-200 dark:border-gray-700">
                    <dt className="text-gray-500 dark:text-gray-400 flex items-center gap-1">
                      <Activity className="h-3 w-3" />
                      Last Activity
                    </dt>
                    <dd className="font-medium text-gray-900 dark:text-white">
                      {run.last_activity_at ? (
                        <>
                          {formatDateTime(run.last_activity_at)}
                          <span className="text-gray-500 dark:text-gray-400 text-xs ml-2">
                            ({formatTimeAgo(run.last_activity_at)})
                          </span>
                          {/* Warn if no activity for over 5 minutes */}
                          {(() => {
                            const lastActivity = new Date(run.last_activity_at).getTime();
                            const now = Date.now();
                            const inactiveMinutes = Math.floor((now - lastActivity) / 60000);
                            if (inactiveMinutes >= 5) {
                              return (
                                <div className="mt-1 flex items-center gap-1 text-amber-600 dark:text-amber-400 text-xs">
                                  <AlertTriangle className="h-3 w-3" />
                                  Inactive for {inactiveMinutes}m (may timeout soon)
                                </div>
                              );
                            }
                            return null;
                          })()}
                        </>
                      ) : (
                        <span className="text-amber-600 dark:text-amber-400">
                          No activity recorded
                        </span>
                      )}
                    </dd>
                  </div>
                )}
              </dl>
            </div>

            {/* Job Metadata Card */}
            <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                <Hash className="h-4 w-4 text-gray-500" />
                Job Metadata
              </h3>
              <dl className="space-y-3 text-sm">
                <div>
                  <dt className="text-gray-500 dark:text-gray-400">Run Type</dt>
                  <dd className="font-medium text-gray-900 dark:text-white">{run.run_type}</dd>
                </div>
                <div>
                  <dt className="text-gray-500 dark:text-gray-400">Origin</dt>
                  <dd className="font-medium text-gray-900 dark:text-white capitalize">{run.origin}</dd>
                </div>
                {queueDefinition && (
                  <>
                    <div>
                      <dt className="text-gray-500 dark:text-gray-400">Queue</dt>
                      <dd className="font-medium text-gray-900 dark:text-white">{queueDefinition.celery_queue}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500 dark:text-gray-400">Timeout</dt>
                      <dd className="font-medium text-gray-900 dark:text-white">{queueDefinition.timeout_seconds}s</dd>
                    </div>
                  </>
                )}
                {run.created_by && (
                  <div>
                    <dt className="text-gray-500 dark:text-gray-400">Created By</dt>
                    <dd className="font-mono text-xs text-gray-900 dark:text-white truncate">{run.created_by}</dd>
                  </div>
                )}
              </dl>
            </div>

            {/* Queue Capabilities */}
            {queueDefinition && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <Zap className="h-4 w-4 text-gray-500" />
                  Queue Capabilities
                </h3>
                <div className="space-y-2">
                  <CapabilityBadge label="Cancel" enabled={queueDefinition.can_cancel} />
                  <CapabilityBadge label="Retry" enabled={queueDefinition.can_retry} />
                  <CapabilityBadge label="Throttled" enabled={queueDefinition.is_throttled} />
                </div>
              </div>
            )}

            {/* Source Configuration Link */}
            {run.run_type === 'sam_pull' && run.config?.search_id && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <Building2 className="h-4 w-4 text-amber-500" />
                  Source Configuration
                </h3>
                <Link
                  href={`/sam/${run.config.search_id}`}
                  className="flex items-center gap-3 p-3 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors"
                >
                  <Building2 className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-amber-800 dark:text-amber-200">
                      View SAM.gov Search Config
                    </span>
                    <div className="text-xs text-amber-600 dark:text-amber-400 font-mono truncate">
                      {run.config.search_id}
                    </div>
                  </div>
                  <ExternalLink className="h-4 w-4 text-amber-500 flex-shrink-0" />
                </Link>
              </div>
            )}

            {run.run_type === 'scrape' && run.config?.collection_id && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <Globe className="h-4 w-4 text-emerald-500" />
                  Source Configuration
                </h3>
                <Link
                  href={`/scrape/${run.config.collection_id}`}
                  className="flex items-center gap-3 p-3 rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 transition-colors"
                >
                  <Globe className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-emerald-800 dark:text-emerald-200">
                      View Scrape Collection
                    </span>
                    <div className="text-xs text-emerald-600 dark:text-emerald-400 font-mono truncate">
                      {run.config.collection_id}
                    </div>
                  </div>
                  <ExternalLink className="h-4 w-4 text-emerald-500 flex-shrink-0" />
                </Link>
              </div>
            )}

            {run.run_type === 'sharepoint_sync' && run.config?.config_id && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <FolderSync className="h-4 w-4 text-purple-500" />
                  Source Configuration
                </h3>
                <Link
                  href={`/sharepoint-sync/${run.config.config_id}`}
                  className="flex items-center gap-3 p-3 rounded-lg border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20 hover:bg-purple-100 dark:hover:bg-purple-900/30 transition-colors"
                >
                  <FolderSync className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-purple-800 dark:text-purple-200">
                      View SharePoint Config
                    </span>
                    <div className="text-xs text-purple-600 dark:text-purple-400 font-mono truncate">
                      {run.config.config_id}
                    </div>
                  </div>
                  <ExternalLink className="h-4 w-4 text-purple-500 flex-shrink-0" />
                </Link>
              </div>
            )}

            {run.run_type === 'procedure' && run.config?.procedure_slug && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <Zap className="h-4 w-4 text-cyan-500" />
                  Source Configuration
                </h3>
                <Link
                  href={`/admin/procedures/${run.config.procedure_slug}/edit`}
                  className="flex items-center gap-3 p-3 rounded-lg border border-cyan-200 dark:border-cyan-800 bg-cyan-50 dark:bg-cyan-900/20 hover:bg-cyan-100 dark:hover:bg-cyan-900/30 transition-colors"
                >
                  <Zap className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-cyan-800 dark:text-cyan-200">
                      View Procedure
                    </span>
                    <div className="text-xs text-cyan-600 dark:text-cyan-400 font-mono truncate">
                      {run.config.procedure_name || run.config.procedure_slug}
                    </div>
                  </div>
                  <ExternalLink className="h-4 w-4 text-cyan-500 flex-shrink-0" />
                </Link>
              </div>
            )}

            {/* Associated Assets */}
            {assets && assets.length > 0 && (
              <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <FileText className="h-4 w-4 text-gray-500" />
                  Associated Assets
                </h3>
                <div className="space-y-2">
                  {assets.map(asset => (
                    <Link
                      key={asset.id}
                      href={`/assets/${asset.id}`}
                      className="block p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-gray-400" />
                        <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {asset.original_filename}
                        </span>
                        <ExternalLink className="h-3 w-3 text-gray-400 ml-auto flex-shrink-0" />
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        {asset.source_type} &middot; {asset.status}
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {/* Configuration */}
            <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                  <Settings className="h-4 w-4 text-gray-500" />
                  Raw Data
                </h3>
              </div>
              <div className="p-4 space-y-4">
                <JsonViewer data={run.config} title="Configuration" defaultExpanded={false} />
                <JsonViewer data={run.progress} title="Progress" defaultExpanded={false} />
                <JsonViewer data={run.results_summary} title="Results Summary" defaultExpanded={false} />
                {run.input_asset_ids && run.input_asset_ids.length > 0 && (
                  <JsonViewer data={run.input_asset_ids} title="Input Asset IDs" defaultExpanded={false} />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CapabilityBadge({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-600 dark:text-gray-400">{label}</span>
      <span className={`text-xs font-medium px-2 py-0.5 rounded ${
        enabled
          ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
          : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500'
      }`}>
        {enabled ? 'Yes' : 'No'}
      </span>
    </div>
  );
}

/**
 * AnimatedValue component - flashes briefly when the value changes.
 * Provides visual feedback for updating metrics across all job types.
 */
function AnimatedValue({ value, className = '' }: { value: unknown; className?: string }) {
  const [isAnimating, setIsAnimating] = useState(false);
  const prevValueRef = useRef<unknown>(value);

  useEffect(() => {
    // Check if value actually changed (not just on mount)
    if (prevValueRef.current !== undefined && prevValueRef.current !== value) {
      setIsAnimating(true);
      const timer = setTimeout(() => setIsAnimating(false), 600);
      return () => clearTimeout(timer);
    }
    prevValueRef.current = value;
  }, [value]);

  // Update ref after comparison
  useEffect(() => {
    prevValueRef.current = value;
  });

  const displayValue = typeof value === 'object' ? JSON.stringify(value) : String(value);

  return (
    <span
      className={`inline-block transition-all duration-300 ${
        isAnimating
          ? 'bg-yellow-200 dark:bg-yellow-600/40 rounded px-1 -mx-1 scale-105'
          : ''
      } ${className}`}
    >
      {displayValue}
    </span>
  );
}

function ProgressDisplay({ progress }: { progress: Record<string, unknown> }) {
  // Handle standard progress format: { current, total, percent, phase, ... }
  const current = progress.current as number | undefined;
  const total = progress.total as number | undefined;
  const percent = progress.percent as number | undefined;
  const phase = progress.phase as string | undefined;
  const unit = progress.unit as string | undefined;

  // Calculate percent if not provided
  const displayPercent = percent ?? (current && total ? Math.round((current / total) * 100) : undefined);

  // Extract additional progress details
  const details = Object.entries(progress).filter(
    ([key]) => !['current', 'total', 'percent', 'phase', 'unit'].includes(key)
  );

  return (
    <div className="space-y-4">
      {/* Progress Bar */}
      {displayPercent !== undefined && (
        <div>
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-gray-600 dark:text-gray-400">
              {phase || 'Progress'}
            </span>
            <span className="font-medium text-gray-900 dark:text-white">
              {current !== undefined && total !== undefined
                ? <><AnimatedValue value={current} /> / {total}{unit ? ` ${unit}` : ''}</>
                : <><AnimatedValue value={displayPercent} />%</>}
            </span>
          </div>
          <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-600 dark:bg-indigo-500 transition-all duration-300"
              style={{ width: `${Math.min(displayPercent, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Additional Progress Details */}
      {details.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {details.map(([key, value]) => (
            <div key={key} className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3">
              <div className="text-xs text-gray-500 dark:text-gray-400 capitalize">
                {key.replace(/_/g, ' ')}
              </div>
              <div className="text-sm font-medium text-gray-900 dark:text-white mt-1">
                <AnimatedValue value={value} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultsSummaryDisplay({ summary }: { summary: Record<string, unknown> }) {
  // Group numeric values as stats, arrays as lists, objects as nested
  const stats: [string, number][] = [];
  const lists: [string, unknown[]][] = [];
  const others: [string, unknown][] = [];

  Object.entries(summary).forEach(([key, value]) => {
    if (typeof value === 'number') {
      stats.push([key, value]);
    } else if (Array.isArray(value)) {
      lists.push([key, value]);
    } else {
      others.push([key, value]);
    }
  });

  return (
    <div className="space-y-4">
      {/* Numeric Stats Grid */}
      {stats.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {stats.map(([key, value]) => {
            const isError = key.toLowerCase().includes('error') || key.toLowerCase().includes('failed');
            const isSuccess = key.toLowerCase().includes('success') || key.toLowerCase().includes('completed') || key.toLowerCase().includes('new');
            return (
              <div
                key={key}
                className={`rounded-lg p-3 ${
                  isError && value > 0
                    ? 'bg-red-50 dark:bg-red-900/20'
                    : isSuccess && value > 0
                    ? 'bg-emerald-50 dark:bg-emerald-900/20'
                    : 'bg-gray-50 dark:bg-gray-800'
                }`}
              >
                <div className="text-xs text-gray-500 dark:text-gray-400 capitalize">
                  {key.replace(/_/g, ' ')}
                </div>
                <div className={`text-lg font-semibold mt-1 ${
                  isError && value > 0
                    ? 'text-red-700 dark:text-red-400'
                    : isSuccess && value > 0
                    ? 'text-emerald-700 dark:text-emerald-400'
                    : 'text-gray-900 dark:text-white'
                }`}>
                  <AnimatedValue value={value.toLocaleString()} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Lists (e.g., errors array) */}
      {lists.map(([key, items]) => (
        <div key={key}>
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 capitalize">
            {key.replace(/_/g, ' ')} ({items.length})
          </h4>
          {items.length > 0 ? (
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {items.slice(0, 20).map((item, idx) => (
                <div
                  key={idx}
                  className="text-sm bg-gray-50 dark:bg-gray-800 rounded p-2 font-mono text-gray-700 dark:text-gray-300"
                >
                  {typeof item === 'object' ? JSON.stringify(item) : String(item)}
                </div>
              ))}
              {items.length > 20 && (
                <div className="text-sm text-gray-500 dark:text-gray-400">
                  ... and {items.length - 20} more
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-gray-500 dark:text-gray-400">None</div>
          )}
        </div>
      ))}

      {/* Other Values */}
      {others.map(([key, value]) => (
        <div key={key}>
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 capitalize">
            {key.replace(/_/g, ' ')}
          </h4>
          <div className="text-sm bg-gray-50 dark:bg-gray-800 rounded p-2 font-mono text-gray-700 dark:text-gray-300">
            {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
          </div>
        </div>
      ))}
    </div>
  );
}

function LogTimeline({ logs, runCreatedAt }: { logs: RunLogEvent[]; runCreatedAt: string }) {
  const [expandedLogs, setExpandedLogs] = useState<Set<string>>(new Set());

  if (logs.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        No log events recorded yet
      </div>
    );
  }

  // Sort logs by created_at ascending (oldest first for timeline)
  const sortedLogs = [...logs].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );

  const toggleExpand = (logId: string) => {
    setExpandedLogs(prev => {
      const next = new Set(prev);
      if (next.has(logId)) {
        next.delete(logId);
      } else {
        next.add(logId);
      }
      return next;
    });
  };

  return (
    <div className="relative">
      {/* Timeline line */}
      <div className="absolute left-4 top-0 bottom-0 w-px bg-gray-200 dark:bg-gray-700" />

      <div className="space-y-4">
        {sortedLogs.map((log, idx) => {
          const levelConfig = LOG_LEVEL_CONFIG[log.level] || LOG_LEVEL_CONFIG.INFO;
          const LevelIcon = levelConfig.icon;
          const isExpanded = expandedLogs.has(log.id);
          const hasContext = log.context && Object.keys(log.context).length > 0;
          const timeSinceStart = formatDuration(runCreatedAt, log.created_at);

          return (
            <div key={log.id} className="relative pl-10">
              {/* Timeline dot */}
              <div className={`absolute left-2 w-5 h-5 rounded-full ${levelConfig.bgColor} flex items-center justify-center`}>
                <LevelIcon className={`h-3 w-3 ${levelConfig.color}`} />
              </div>

              <div
                className={`rounded-lg border ${
                  log.level === 'ERROR'
                    ? 'border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-900/10'
                    : log.level === 'WARN'
                    ? 'border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10'
                    : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50'
                }`}
              >
                <div
                  className={`p-3 ${hasContext ? 'cursor-pointer' : ''}`}
                  onClick={() => hasContext && toggleExpand(log.id)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${levelConfig.bgColor} ${levelConfig.color}`}>
                          {log.level}
                        </span>
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">
                          {log.event_type}
                        </span>
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          +{timeSinceStart}
                        </span>
                      </div>
                      <p className="mt-1 text-sm text-gray-900 dark:text-white">
                        {log.message}
                      </p>
                    </div>
                    {hasContext && (
                      <button className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                    )}
                  </div>
                </div>

                {/* Expanded context */}
                {isExpanded && hasContext && (
                  <div className="px-3 pb-3 border-t border-gray-200 dark:border-gray-700">
                    <pre className="mt-2 p-2 text-xs bg-gray-900 text-gray-100 rounded overflow-x-auto">
                      {JSON.stringify(log.context, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
