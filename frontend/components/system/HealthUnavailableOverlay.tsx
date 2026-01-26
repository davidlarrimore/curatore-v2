import Link from 'next/link'

interface HealthUnavailableOverlayProps {
  isVisible: boolean
}

export function HealthUnavailableOverlay({ isVisible }: HealthUnavailableOverlayProps) {
  if (!isVisible) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
      <div className="card w-full max-w-md mx-4 shadow-md animate-slide-up">
        <div className="px-6 pt-6 pb-4 border-b border-slate-200">
          <div className="flex items-center gap-4">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-blue-50">
              <svg
                viewBox="0 0 120 120"
                className="h-12 w-12 text-blue-600 stopwatch-pulse"
                aria-hidden="true"
              >
                <circle cx="60" cy="62" r="38" fill="none" stroke="currentColor" strokeWidth="6" />
                <circle cx="60" cy="62" r="4" fill="currentColor" />
                <line
                  x1="60"
                  y1="62"
                  x2="60"
                  y2="36"
                  stroke="currentColor"
                  strokeWidth="6"
                  strokeLinecap="round"
                  className="stopwatch-hand"
                />
                <rect x="48" y="16" width="24" height="12" rx="4" fill="currentColor" />
                <rect x="78" y="28" width="14" height="10" rx="4" fill="currentColor" />
              </svg>
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Hold tight</h2>
              <p className="text-sm text-slate-600">Curatore is restarting its services.</p>
            </div>
          </div>
        </div>

        <div className="px-6 py-5 text-sm text-slate-600">
          <p>We are reconnecting to the backend. This page will resume automatically once the system is healthy.</p>
        </div>

        <div className="px-6 pb-6 pt-1 flex items-center justify-between text-sm">
          <Link
            href="/login"
            className="text-blue-600 font-medium hover:text-blue-700 transition-colors"
          >
            Go to login
          </Link>
          <Link
            href="/"
            className="text-slate-600 font-medium hover:text-slate-800 transition-colors"
          >
            Back to dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
