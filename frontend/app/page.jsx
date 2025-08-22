'use client'

import { useEffect, useState } from 'react'
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function Page() {
  const [health, setHealth] = useState('checking...')
  const [items, setItems] = useState([])

  useEffect(() => {
    fetch(`${API_URL}/api/health`)
      .then(r => r.json())
      .then(d => setHealth(d.status ?? 'unknown'))
      .catch(() => setHealth('error'))

    fetch(`${API_URL}/api/items`)
      .then(r => r.json())
      .then(d => setItems(d))
      .catch(() => setItems([]))
  }, [])

  return (
    <main className="min-h-screen p-6 bg-gray-50">
      <div className="max-w-3xl mx-auto space-y-6">
        <header className="text-center">
          <h1 className="text-3xl font-semibold">Next.js + Tailwind + FastAPI (Docker)</h1>
          <p className="text-gray-600 mt-2">Starter project is up and running.</p>
        </header>

        <section className="grid md:grid-cols-2 gap-4">
          <div className="rounded-2xl border bg-white p-5 shadow-sm">
            <h2 className="text-xl font-medium mb-2">Backend Health</h2>
            <p className="text-sm text-gray-500">API URL: <code>{API_URL}</code></p>
            <div className="mt-3 inline-flex items-center rounded-full border px-4 py-2">
              <span className="text-sm">Status: </span>
              <span className="ml-2 font-semibold">{health}</span>
            </div>
          </div>

          <div className="rounded-2xl border bg-white p-5 shadow-sm">
            <h2 className="text-xl font-medium mb-2">Items (from API)</h2>
            <ul className="list-disc pl-6 space-y-1">
              {items.map(it => (
                <li key={it.id} className="text-gray-800">{it.name}</li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </main>
  )
}
