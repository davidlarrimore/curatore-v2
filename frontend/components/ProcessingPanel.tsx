// components/ProcessingPanel.tsx

'use client'

import { useState, useEffect, useRef } from 'react';
import { ProcessingResult, FileInfo, ProcessingOptions } from '@/types';
import { processingApi, jobsApi, utils, fileApi, systemApi } from '@/lib/api';
import toast from 'react-hot-toast';

interface ProcessingLog {
  timestamp: string;
  level: 'info' | 'success' | 'warning' | 'error';
  message: string;
}

type PanelState = 'minimized' | 'normal' | 'fullscreen';

interface JobState {
  job_id: string;
  document_id: string;
  filename: string;
  status: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE' | 'UNKNOWN';
  started_at?: string;
  extractor_info?: string;
  result?: ProcessingResult;
}

interface ProcessingPanelProps {
  selectedFiles: FileInfo[];
  processingOptions: ProcessingOptions;
  onProcessingComplete: (results: ProcessingResult[]) => void;
  onResultUpdate?: (results: ProcessingResult[]) => void;
  onError: (error: string) => void;
  isVisible: boolean;
  onClose: () => void;
  resetTrigger?: number;
  onPanelStateChange?: (state: PanelState | 'hidden') => void;
  sourceType?: 'local' | 'upload';
}

export function ProcessingPanel({
  selectedFiles,
  processingOptions,
  onProcessingComplete,
  onResultUpdate,
  onError,
  isVisible,
  onClose,
  resetTrigger = 0,
  onPanelStateChange,
  sourceType = 'local'
}: ProcessingPanelProps) {
  const [panelState, setPanelState] = useState<PanelState>('minimized');
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentFile, setCurrentFile] = useState<string>('');
  const [results, setResults] = useState<ProcessingResult[]>([]);
  const [logs, setLogs] = useState<ProcessingLog[]>([]);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const [processingStartTime, setProcessingStartTime] = useState<number>(0);
  const [processingComplete, setProcessingComplete] = useState(false);
  // NEW: State for quick download actions
  const [quickDownloadLoading, setQuickDownloadLoading] = useState<string>('');
  // NEW: Track individual job states for live status display
  const [jobStates, setJobStates] = useState<Record<string, JobState>>({});
  // NEW: Timer for live elapsed time display
  const [currentTime, setCurrentTime] = useState(Date.now());

  // Update timer every second for live elapsed time
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Helper function to calculate elapsed time
  const getElapsedTime = (startedAt?: string): string => {
    if (!startedAt) return '';
    try {
      // Backend returns UTC timestamps without 'Z' suffix
      // Append 'Z' if not present to ensure proper UTC parsing
      let utcTimestamp = startedAt;
      if (!startedAt.endsWith('Z') && !startedAt.includes('+') && !startedAt.includes('-', 10)) {
        utcTimestamp = startedAt + 'Z';
      }

      // Parse the ISO string to timestamp
      const start = new Date(utcTimestamp).getTime();

      // If parsing failed, return empty
      if (isNaN(start)) return '';

      // Calculate elapsed time (current - start should be positive)
      const elapsed = Math.floor((currentTime - start) / 1000);

      // If negative (clock skew or future date), return empty
      if (elapsed < 0) return '';

      if (elapsed < 60) return `${elapsed}s`;
      const minutes = Math.floor(elapsed / 60);
      const seconds = elapsed % 60;
      return `${minutes}m ${seconds}s`;
    } catch (e) {
      return '';
    }
  };

  // Map raw extractor info to a normalized badge (Docling vs Default)
  const resolveExtractorBadge = (raw?: string) => {
    if (!raw) return null;

    const chain = raw.replace(/->/g, "→").trim();
    const finalSegment = chain.split("→").pop()?.trim() || chain;
    const normalized = finalSegment.toLowerCase();

    const isDocling = normalized.includes('docling');
    const isDefault = normalized.includes('extraction') || normalized.includes('default');

    if (!isDocling && !isDefault) return null;

    return {
      label: isDocling ? 'Docling' : 'Extraction',
      className: isDocling
        ? 'bg-indigo-900 text-indigo-200 border border-indigo-700'
        : 'bg-gray-800 text-gray-200 border border-gray-600',
      title: chain,
    };
  };

  // Notify parent of panel state changes
  useEffect(() => {
    if (onPanelStateChange) {
      if (isVisible) {
        onPanelStateChange(panelState);
      } else {
        onPanelStateChange('hidden');
      }
    }
  }, [panelState, isVisible, onPanelStateChange]);

  // Reset internal state when resetTrigger changes
  useEffect(() => {
    if (resetTrigger > 0) {
      resetInternalState();
    }
  }, [resetTrigger]);

  const resetInternalState = () => {
    setPanelState('minimized');
    setIsProcessing(false);
    setProgress(0);
    setCurrentFile('');
    setResults([]);
    setLogs([]);
    setProcessingStartTime(0);
    setProcessingComplete(false);
    setQuickDownloadLoading('');
    setJobStates({});
  };

  // Start processing when panel becomes visible
  useEffect(() => {
    if (isVisible && selectedFiles.length > 0 && !isProcessing && !processingComplete) {
      processFiles();
    }
  }, [isVisible, selectedFiles]);

  // Handle fullscreen body scroll lock
  useEffect(() => {
    if (panelState === 'fullscreen') {
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = 'unset';
      };
    } else {
      document.body.style.overflow = 'unset';
    }
  }, [panelState]);

  const scrollToBottom = () => {
    try {
      const el = logContainerRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    } catch {}
  };

  const addLog = (level: ProcessingLog['level'], message: string, ts?: string) => {
    const timestamp = ts ? new Date(ts).toLocaleTimeString() : new Date().toLocaleTimeString();
    const newLog: ProcessingLog = { timestamp, level, message };
    setLogs(prev => {
      const next = [...prev.slice(-200), newLog];
      // Defer scroll to after DOM update
      setTimeout(scrollToBottom, 0);
      return next;
    });
  };

  const getLogIcon = (level: ProcessingLog['level']) => {
    switch (level) {
      case 'success': return '✅';
      case 'warning': return '⚠️';
      case 'error': return '❌';
      default: return 'ℹ️';
    }
  };

  const updateResults = (newResults: ProcessingResult[]) => {
    setResults(newResults);
    if (onResultUpdate) {
      onResultUpdate(newResults);
    }
  };

  // NEW: Quick download functions for the processing panel
  const quickDownloadRAGReady = async () => {
    const ragReadyResults = results.filter(r => r.pass_all_thresholds);
    if (ragReadyResults.length === 0) {
      toast.error('No RAG-ready files available yet');
      return;
    }

    setQuickDownloadLoading('rag');
    try {
      const timestamp = utils.generateTimestamp();
      const zipName = `curatore_rag_ready_${timestamp}.zip`;
      
      const blob = await fileApi.downloadRAGReadyDocuments(zipName);
      utils.downloadBlob(blob, zipName);
      
      addLog('success', `Downloaded ${ragReadyResults.length} RAG-ready files as ZIP`);
      toast.success(`Downloaded ${ragReadyResults.length} RAG-ready files`, { icon: '🎯' });
    } catch (error) {
      console.error('Quick RAG download failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Download failed';
      addLog('error', `Quick RAG download failed: ${errorMessage}`);
      toast.error('Failed to download RAG-ready files');
    } finally {
      setQuickDownloadLoading('');
    }
  };

  const quickDownloadAll = async () => {
    const successfulResults = results.filter(r => r.success);
    if (successfulResults.length === 0) {
      toast.error('No processed files available yet');
      return;
    }

    setQuickDownloadLoading('all');
    try {
      const allDocumentIds = successfulResults.map(r => r.document_id);
      const timestamp = utils.generateTimestamp();
      const zipName = `curatore_all_processed_${timestamp}.zip`;
      
      const blob = await fileApi.downloadBulkDocuments(allDocumentIds, 'individual', zipName);
      utils.downloadBlob(blob, zipName);
      
      addLog('success', `Downloaded all ${successfulResults.length} processed files as ZIP`);
      toast.success(`Downloaded ${successfulResults.length} processed files`, { icon: '📦' });
    } catch (error) {
      console.error('Quick download all failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Download failed';
      addLog('error', `Quick download all failed: ${errorMessage}`);
      toast.error('Failed to download all files');
    } finally {
      setQuickDownloadLoading('');
    }
  };

  const processFiles = async () => {
    if (selectedFiles.length === 0) {
      onError('No files selected for processing');
      return;
    }

    setIsProcessing(true);
    setProgress(0);
    setResults([]);
    setLogs([]);
    setProcessingStartTime(Date.now());
    setProcessingComplete(false);

    addLog('info', `Queueing ${selectedFiles.length} files for background processing...`);
    addLog('info', `Vector optimization: ${processingOptions.auto_optimize ? 'ON' : 'OFF'}`);

    // Quick pre-flight: check backend health with short retries to provide a friendly UX when backend is restarting
    const healthTimeoutMs = 2500;
    const healthRetries = 3;
    const sleep = (ms: number) => new Promise(res => setTimeout(res, ms));
    const withTimeout = async <T,>(p: Promise<T>, ms: number) => {
      return await Promise.race<T | never>([
        p,
        new Promise<never>((_, rej) => setTimeout(() => rej(new Error('Health check timeout')), ms))
      ]);
    };
    try {
      let ok = false;
      for (let i = 0; i < healthRetries; i++) {
        try {
          if (i === 0) addLog('info', 'Probing backend health…');
          await withTimeout(systemApi.getHealth(), healthTimeoutMs);
          ok = true;
          break;
        } catch (e) {
          if (i === 0) {
            addLog('warning', 'Backend not responding yet. Retrying…');
            toast.loading('Backend is starting… retrying', { id: 'health-retry' });
          }
          await sleep(1000 * (i + 1));
        }
      }
      if (!ok) {
        toast.error('Backend unavailable. Please try again shortly.', { id: 'health-retry' });
        addLog('error', 'Backend unavailable. Aborting processing start.');
        setIsProcessing(false);
        return;
      }
      toast.dismiss('health-retry');
      addLog('success', 'Backend healthy. Enqueueing jobs…');
    } catch {
      // Non-fatal: proceed, but inform user
      addLog('warning', 'Proceeding without health confirmation.');
    }

    // 1) Enqueue a job for all selected documents
    const docIds = selectedFiles.map(f => f.document_id);
    const jobMap: Record<string, { job_id: string; filename: string }> = {};
    const logSeen: Record<string, number> = {};

    let jobId: string | null = null;
    try {
      const job = await jobsApi.createJob(undefined, {
        document_ids: docIds,
        options: processingOptions as any,
        name: `${sourceType === 'upload' ? 'Upload' : 'Batch'} processing (${docIds.length} documents)`,
        description: `Processing ${docIds.length} documents from ${sourceType}`,
        start_immediately: true,
      });
      jobId = job.id;
      addLog('success', `Job created: ${job.name || job.id}`);
    } catch (err: any) {
      addLog('error', `Failed to create job: ${err?.message || 'unknown error'}`);
      toast.error('Failed to create job');
      setIsProcessing(false);
      return;
    }

    for (const f of selectedFiles) {
      jobMap[f.document_id] = { job_id: jobId, filename: f.filename };
    }

    const totalJobs = Object.keys(jobMap).length;
    if (!jobId || totalJobs === 0) {
      setIsProcessing(false);
      setProcessingComplete(true);
      return;
    }

    // Initialize job states as PENDING
    const initialJobStates: Record<string, JobState> = {};
    for (const [docId, { job_id, filename }] of Object.entries(jobMap)) {
      initialJobStates[docId] = {
        job_id,
        document_id: docId,
        filename,
        status: 'PENDING'
      };
    }
    setJobStates(initialJobStates);

    // Persist active job group for status bar summary
    try {
      const group = { batch_id: null, job_ids: Object.values(jobMap).map(j => j.job_id), ts: Date.now() };
      localStorage.setItem('curatore:active_jobs', JSON.stringify(group));
    } catch {}

    // 2) Poll all jobs until done
    // Process logs and statuses from backend only (avoid duplicate messages)
    const processedResults: ProcessingResult[] = [];
    const done: Record<string, boolean> = {};

    const pollInterval = parseInt(process.env.NEXT_PUBLIC_JOB_POLL_INTERVAL_MS || '2500', 10);

    const pollOnce = async () => {
      let completed = 0;
      const newJobStates: Record<string, JobState> = {};

      const jobIds = Array.from(new Set(Object.values(jobMap).map(j => j.job_id)));

      for (const job_id of jobIds) {
        let status: any;
        try {
          status = await jobsApi.getJob(undefined, job_id);
        } catch {
          continue;
        }

        const backendLogs = Array.isArray(status.recent_logs)
          ? [...status.recent_logs].reverse()
          : Array.isArray(status.logs)
            ? [...status.logs].reverse()
            : [];

        const seen = logSeen[job_id] || 0;
        if (backendLogs.length > seen) {
          for (let i = seen; i < backendLogs.length; i++) {
            const entry = backendLogs[i];
            const rawLevel = ((entry.level || 'info') as string).toLowerCase();
            const lvl = (['info', 'success', 'warning', 'error'].includes(rawLevel)
              ? rawLevel
              : 'info') as ProcessingLog['level'];
            const rawMsg = typeof entry.message === 'string' ? entry.message : JSON.stringify(entry.message);
            const docId = entry.document_id as string | undefined;
            const filename = docId && jobMap[docId]?.filename ? jobMap[docId].filename : 'Job';
            const msg = `${filename} - ${rawMsg}`;
            addLog(lvl, msg, entry.timestamp || entry.ts);
          }
          logSeen[job_id] = backendLogs.length;
        }

        const documents = Array.isArray(status.documents) ? status.documents : [];
        const documentMap: Record<string, any> = {};
        for (const doc of documents) {
          if (doc?.document_id) documentMap[doc.document_id] = doc;
        }

        for (const [docId, { filename }] of Object.entries(jobMap)) {
          if (jobMap[docId].job_id !== job_id) continue;
          if (done[docId]) { completed++; continue; }

          const docInfo = documentMap[docId];
          const rawStatus = (docInfo?.status || '').toUpperCase();
          const mappedStatus = rawStatus === 'COMPLETED'
            ? 'SUCCESS'
            : rawStatus === 'FAILED' || rawStatus === 'CANCELLED'
              ? 'FAILURE'
              : rawStatus === 'RUNNING'
                ? 'STARTED'
                : rawStatus === 'PENDING' || rawStatus === 'QUEUED'
                  ? 'PENDING'
                  : 'UNKNOWN';

          const docLogs = backendLogs.filter((entry: any) => entry.document_id === docId);
          let extractorInfo: string | undefined;
          for (let i = docLogs.length - 1; i >= 0; i--) {
            const msg = typeof docLogs[i].message === 'string' ? docLogs[i].message : '';
            if (msg.startsWith('Extractor:')) {
              const extractorText = msg.substring('Extractor:'.length).trim();
              if (extractorText.includes('Docling')) {
                extractorInfo = 'Docling';
              } else if (extractorText.includes('extraction-service')) {
                extractorInfo = 'Extraction';
              }
            }
            if (msg.includes('Extractor used:')) {
              if (msg.includes('extraction-service')) {
                extractorInfo = 'Extraction';
              } else if (msg.includes('docling')) {
                extractorInfo = 'Docling';
              }
              break;
            }
          }

          newJobStates[docId] = {
            job_id,
            document_id: docId,
            filename,
            status: mappedStatus as any,
            started_at: docInfo?.started_at || status.started_at,
            extractor_info: extractorInfo,
          };

          if (mappedStatus === 'SUCCESS') {
            try {
              const res = await processingApi.getProcessingResult(docId);
              processedResults.push(res);
              updateResults([...processedResults]);
              done[docId] = true;
              completed++;
            } catch (e) {
              // Keep polling until result is available
            }
          } else if (mappedStatus === 'FAILURE') {
            const failedResult: ProcessingResult = {
              document_id: docId,
              filename,
              status: 'failed',
              success: false,
              message: docInfo?.error_message || 'Processing failed',
              conversion_score: 0,
              pass_all_thresholds: false,
              vector_optimized: false
            };
            processedResults.push(failedResult);
            updateResults([...processedResults]);
            done[docId] = true;
            completed++;
          }
        }
      }

      setJobStates(newJobStates);
      setProgress((completed / totalJobs) * 100);
      return completed === totalJobs;
    };

    try {
      // Loop with polling delay
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const allDone = await pollOnce();
        if (allDone) break;
        await new Promise(res => setTimeout(res, pollInterval));
      }

      // Final sanity refresh: pull fresh results from API to ensure UI reflects final state
      try {
        const allIds = Object.keys(jobMap);
        const fetched = await Promise.all(
          allIds.map(async (id) => {
            try {
              return await processingApi.getProcessingResult(id);
            } catch {
              return null;
            }
          })
        );
        const byId: Record<string, ProcessingResult> = {};
        for (const r of processedResults) byId[r.document_id] = r;
        for (const r of fetched) if (r && r.document_id) byId[r.document_id] = r;
        const merged = Object.values(byId);
        updateResults(merged);
        // replace local ref for summary
        processedResults.length = 0; processedResults.push(...merged);
      } catch {}

      const successful = processedResults.filter(r => r.success).length;
      const failed = processedResults.length - successful;
      const ragReady = processedResults.filter(r => r.pass_all_thresholds).length;
      const processingTime = (Date.now() - processingStartTime) / 1000;

      addLog('success', `Processing complete!`);
      addLog('info', `Summary: ${successful} successful, ${failed} failed, ${ragReady} RAG-ready`);
      addLog('info', `Total time: ${utils.formatDuration(processingTime)}`);

      setProcessingComplete(true);
      try { localStorage.setItem('curatore:active_jobs', JSON.stringify({ batch_id: null, job_ids: Object.values(jobMap).map(j => j.job_id), ts: Date.now(), done: true })); } catch {}
      onProcessingComplete(processedResults);

      toast.success(
        `Processing complete! ${ragReady} of ${successful} files are RAG-ready`,
        { duration: 6000, icon: '🎉' }
      );
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      addLog('error', `Processing failed: ${errorMessage}`);
      onError(`Processing failed: ${errorMessage}`);
      setProcessingComplete(false);
    } finally {
      setIsProcessing(false);
      setCurrentFile('');
    }
  };

  // Keep component mounted to continue background polling even when hidden
  const visibilityClass = isVisible ? '' : 'hidden';

  const successful = results.filter(r => r.success).length;
  const failed = results.length - successful;
  const ragReady = results.filter(r => r.pass_all_thresholds).length;

  // Panel positioning and size with proper z-index and sidebar awareness
  const getPanelClasses = () => {
    // Base classes with proper z-index
    const baseClasses = "fixed bg-gray-900 border-t border-gray-700 shadow-2xl transition-all duration-300 ease-in-out z-20 flex flex-col";
    
    // Use CSS custom properties for sidebar width awareness
    const sidebarStyle = {
      left: 'var(--sidebar-width, 16rem)',
      right: '0'
    };
    
    switch (panelState) {
      case 'minimized':
        return {
          className: `${baseClasses} h-10`,
          style: { 
            ...sidebarStyle,
            // Use safe offset to guarantee no overlap across DPR/zoom
            bottom: 'var(--statusbar-safe-offset, calc(var(--statusbar-offset, var(--statusbar-height, 40px)) + 2px))'
          }
        };
      case 'fullscreen':
        return {
          className: `${baseClasses} overflow-hidden`,
          style: { 
            ...sidebarStyle,
            top: '4rem', // Below top navigation
            bottom: 'var(--statusbar-offset, var(--statusbar-height, 40px))' // Align exactly above the status bar
          }
        };
      case 'normal':
      default:
        return {
          className: `${baseClasses} overflow-hidden`,
          style: { 
            ...sidebarStyle,
            height: '360px', // Increased height for better content space
            bottom: 'var(--statusbar-offset, var(--statusbar-height, 40px))' // Align exactly above the status bar
          }
        };
    }
  };

  return (
    <div className={`${visibilityClass} ${getPanelClasses().className}`} style={getPanelClasses().style}>
      {/* Header - Dark theme to match status bar but darker */}
      <div 
        className="flex items-center justify-between py-2 px-3 border-b border-gray-600 bg-gray-800 cursor-pointer flex-shrink-0"
        onClick={() => setPanelState(panelState === 'minimized' ? 'normal' : 'minimized')}
      >
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            {isProcessing ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-400"></div>
            ) : processingComplete ? (
              <span className="text-green-400">✅</span>
            ) : (
              <span className="text-blue-400">📄</span>
            )}
            <h3 className="font-medium text-gray-100">
              {isProcessing 
                ? `Processing Documents... (${Math.round(progress)}%)`
                : processingComplete
                  ? 'Processing Complete'
                  : 'Document Processing'
              }
            </h3>
          </div>
          
          {/* Summary stats - Always visible */}
          <div className="flex items-center space-x-4 text-sm text-gray-300">
            <span>{selectedFiles.length} files</span>
            {results.length > 0 && (
              <>
                <span>•</span>
                <span className="text-green-400">{successful} success</span>
                <span>•</span>
                <span className="text-blue-400">{ragReady} RAG-ready</span>
              </>
            )}
            {currentFile && isProcessing && (
              <>
                <span>•</span>
                <span className="text-blue-400">Processing: {currentFile}</span>
              </>
            )}
          </div>
        </div>

        {/* Header Controls with Progress */}
        <div className="flex items-center space-x-2">
          {(isProcessing || progress > 0) && (
            <div className="hidden md:flex items-center space-x-2 mr-2" onClick={(e) => e.stopPropagation()}>
              <span className="text-xs text-gray-300 w-10 text-right">{Math.round(progress)}%</span>
              <div className="w-32 bg-gray-700 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}
          {/* Minimize/Restore */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setPanelState(panelState === 'minimized' ? 'normal' : 'minimized');
            }}
            className="p-2 hover:bg-gray-700 rounded-lg transition-colors text-gray-300 hover:text-gray-100"
            title={panelState === 'minimized' ? 'Restore' : 'Minimize'}
          >
            {panelState === 'minimized' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 14l9-9 3 3L9 18l-6-6z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
              </svg>
            )}
          </button>

          {/* Fullscreen */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setPanelState(panelState === 'fullscreen' ? 'normal' : 'fullscreen');
            }}
            className="p-2 hover:bg-gray-700 rounded-lg transition-colors text-gray-300 hover:text-gray-100"
            title={panelState === 'fullscreen' ? 'Exit Fullscreen' : 'Fullscreen'}
          >
            {panelState === 'fullscreen' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.5 3.5M15 15v4.5M15 15h4.5M15 15l5.5 5.5M15 9h4.5M15 9V4.5M15 9l5.5-5.5M9 15H4.5M9 15v4.5M9 15l-5.5 5.5" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
              </svg>
            )}
          </button>

          {/* Close */}
          {processingComplete && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onClose();
              }}
              className="p-2 hover:bg-gray-700 rounded-lg transition-colors text-gray-300 hover:text-gray-100"
              title="Close"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Content (hidden when minimized) */}
      {panelState !== 'minimized' && (
        <div className="flex-1 overflow-hidden min-h-0">
          <div className="h-full p-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 h-full">
              {/* Processing Results - LEFT COLUMN (50%) */}
              <div className="flex flex-col space-y-4 h-full min-h-0">
                {/* Current File - Fixed height */}
                {currentFile && (
                  <div className="flex items-center space-x-2 text-sm text-gray-300 flex-shrink-0">
                    <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-400"></div>
                    <span>Processing: <strong className="text-gray-100">{currentFile}</strong></span>
                  </div>
                )}

                {/* Stats Grid removed: incorporate status into each result item */}



                {/* Results List - Scrollable (always visible) */}
                <div className="border border-gray-600 rounded-lg flex flex-col flex-1 min-h-0">
                  <div className="p-3 border-b border-gray-600 bg-gray-800 flex-shrink-0">
                    <h4 className="font-medium text-gray-200">Processing Results</h4>
                  </div>
                  <div className="flex-1 overflow-y-auto p-2 space-y-1 scrollbar-thin scrollbar-thumb-gray-400 scrollbar-track-gray-800">
                    {Object.keys(jobStates).length === 0 && results.length === 0 ? (
                      <div className="p-3 text-xs text-gray-400">No jobs yet. Jobs will appear here as they start.</div>
                    ) : (
                      <>
                        {/* Show active jobs (queued or processing) */}
                        {Object.values(jobStates)
                          .filter(job => job.status === 'PENDING' || job.status === 'STARTED')
                          .map((job) => {
                            const extractorBadge = resolveExtractorBadge(job.extractor_info);
                            return (
                              <div
                                key={job.document_id}
                                className={`flex items-center justify-between p-2 rounded text-sm ${
                                  job.status === 'PENDING' ? 'bg-gray-800 text-gray-400' : 'bg-gray-700'
                                }`}
                              >
                                <div className="flex items-center space-x-2 min-w-0 flex-1">
                                  <span className="flex-shrink-0">
                                    {job.status === 'PENDING' ? '⏳' : (
                                      <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-400"></div>
                                    )}
                                  </span>
                                  <span className="text-sm font-medium truncate text-gray-200">{utils.getDisplayFilename(job.filename)}</span>
                                </div>
                                <div className="flex items-center space-x-2 flex-shrink-0">
                                  {/* Status badge */}
                                  {job.status === 'PENDING' ? (
                                    <span className="px-2 py-0.5 rounded text-xs bg-gray-700 text-gray-400 border border-gray-600">Queued</span>
                                  ) : (
                                    <>
                                      <span className="px-2 py-0.5 rounded text-xs bg-blue-900 text-blue-300 border border-blue-700">
                                        Processing
                                      </span>
                                      {/* Elapsed time */}
                                      {job.started_at && (
                                        <span className="px-2 py-0.5 rounded text-xs bg-gray-800 text-gray-300 border border-gray-600 font-mono">
                                          {getElapsedTime(job.started_at)}
                                        </span>
                                      )}
                                      {/* Extractor info */}
                                      {extractorBadge && (
                                        <span className={`px-2 py-0.5 rounded text-xs max-w-xs truncate ${extractorBadge.className}`} title={extractorBadge.title}>
                                          Extractor: {extractorBadge.label}
                                        </span>
                                      )}
                                    </>
                                  )}
                                </div>
                              </div>
                            );
                          })}

                        {/* Show completed jobs */}
                        {results.map((result, index) => {
                          const extractorBadge = resolveExtractorBadge(
                            result.conversion_result?.extraction_engine || jobStates[result.document_id]?.extractor_info
                          );

                          return (
                            <div key={index} className="flex items-center justify-between p-2 hover:bg-gray-700 rounded text-sm">
                              <div className="flex items-center space-x-2 min-w-0 flex-1">
                                <span className="flex-shrink-0">
                                  {result.success ? (result.pass_all_thresholds ? '✅' : '⚠️') : '❌'}
                                </span>
                                <span className="text-sm font-medium truncate text-gray-200">{utils.getDisplayFilename(result.filename)}</span>
                              </div>
                              <div className="flex items-center space-x-2 flex-shrink-0">
                                {/* Primary status badge */}
                                {result.pass_all_thresholds ? (
                                  <span className="px-2 py-0.5 rounded text-xs bg-blue-900 text-blue-300 border border-blue-700">RAG Ready</span>
                                ) : result.success ? (
                                  <span className="px-2 py-0.5 rounded text-xs bg-green-900 text-green-300 border border-green-700">Successful</span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded text-xs bg-red-900 text-red-300 border border-red-700">Failed</span>
                                )}
                                {/* Extractor badge */}
                                {extractorBadge && (
                                  <span className={`px-2 py-0.5 rounded text-xs ${extractorBadge.className}`} title={extractorBadge.title}>
                                    Extractor: {extractorBadge.label}
                                  </span>
                                )}
                                {/* Conversion score */}
                                <span className="px-2 py-0.5 rounded text-xs bg-gray-800 text-gray-300 border border-gray-600">Score: {result.conversion_score}%</span>
                                {/* Optimization flag */}
                                {result.vector_optimized && (
                                  <span className="px-2 py-0.5 rounded text-xs bg-purple-900 text-purple-300 border border-purple-700">Optimized</span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Processing Log - RIGHT COLUMN (50%) */}
              <div className="border border-gray-600 rounded-lg flex flex-col bg-gray-900 h-full min-h-0">
                <div className="flex items-center justify-between p-3 border-b border-gray-600 bg-gray-800 flex-shrink-0">
                  <h4 className="font-medium text-gray-200">Processing Log</h4>
                  <div className="flex items-center space-x-2">
                    <span className="text-xs text-gray-400">{logs.length} entries</span>
                    {logs.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setLogs([])}
                        className="text-xs text-gray-400 hover:text-gray-200 underline"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>
                
                <div className="bg-black text-green-400 font-mono text-xs flex-1 overflow-hidden relative min-h-0">
                  {logs.length === 0 ? (
                    <div className="p-4 text-center text-gray-500 h-full flex items-center justify-center">
                      <p>Processing log will appear here...</p>
                    </div>
                  ) : (
                    <div ref={logContainerRef} className="p-2 h-full overflow-y-auto scrollbar-thin scrollbar-thumb-green-400 scrollbar-track-gray-800">
                      {logs.map((log, index) => (
                        <div key={index} className="flex items-start space-x-2 mb-1 min-h-[1.2rem]">
                          <span className="text-gray-400 text-xs flex-shrink-0 w-20 font-mono">{log.timestamp}</span>
                          <span className="flex-shrink-0">{getLogIcon(log.level)}</span>
                          <span className={`flex-1 break-words ${
                            log.level === 'error' ? 'text-red-400' :
                            log.level === 'warning' ? 'text-yellow-400' :
                            log.level === 'success' ? 'text-green-400' :
                            'text-gray-300'
                          }`}>
                            {log.message}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
