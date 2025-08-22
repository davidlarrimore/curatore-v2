'use client'

import { useEffect, useState } from 'react'
import { FileUpload } from '../components/FileUpload'
import { ProcessingResults } from '../components/ProcessingResults'
import { HealthCheck } from '../components/HealthCheck'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function Page() {
  const [health, setHealth] = useState('checking...')
  const [llmConnected, setLlmConnected] = useState(false)
  const [supportedFormats, setSupportedFormats] = useState([])
  const [documents, setDocuments] = useState([])
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    // Check API health
    fetch(`${API_URL}/api/health`)
      .then(r => r.json())
      .then(d => {
        setHealth(d.status ?? 'unknown')
        setLlmConnected(d.llm_connected ?? false)
      })
      .catch(() => setHealth('error'))

    // Get supported formats
    fetch(`${API_URL}/api/config/supported-formats`)
      .then(r => r.json())
      .then(d => setSupportedFormats(d.supported_extensions || []))
      .catch(console.error)

    // Load existing documents
    loadDocuments()
  }, [])

  const loadDocuments = () => {
    fetch(`${API_URL}/api/documents`)
      .then(r => r.json())
      .then(d => setDocuments(d || []))
      .catch(console.error)
  }

  const handleFileUpload = async (files) => {
    setIsLoading(true)
    const uploadedDocs = []

    for (const file of files) {
      try {
        console.log(`Uploading file: ${file.name}, size: ${file.size}`)
        
        const formData = new FormData()
        formData.append('file', file)

        const uploadResponse = await fetch(`${API_URL}/api/documents/upload`, {
          method: 'POST',
          body: formData
        })

        if (!uploadResponse.ok) {
          const errorText = await uploadResponse.text()
          throw new Error(`Upload failed (${uploadResponse.status}): ${errorText}`)
        }

        const uploadResult = await uploadResponse.json()
        console.log(`Upload successful:`, uploadResult)
        uploadedDocs.push(uploadResult)

      } catch (error) {
        console.error(`Failed to upload ${file.name}:`, error)
        alert(`Failed to upload ${file.name}: ${error.message}`)
      }
    }

    if (uploadedDocs.length > 0) {
      console.log(`Processing ${uploadedDocs.length} uploaded documents...`)
      // Automatically process uploaded documents
      await processDocuments(uploadedDocs.map(doc => doc.document_id))
    }
    
    setIsLoading(false)
  }

  const processDocuments = async (documentIds) => {
    setIsLoading(true)
    
    try {
      const response = await fetch(`${API_URL}/api/documents/batch/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          document_ids: documentIds,
          options: {
            auto_optimize: true,
            ocr_settings: {
              language: "eng",
              psm: 3
            },
            quality_thresholds: {
              conversion: 70,
              clarity: 7,
              completeness: 7,
              relevance: 7,
              markdown: 7
            }
          }
        })
      })

      if (!response.ok) {
        throw new Error(`Processing failed: ${response.statusText}`)
      }

      await response.json()
      loadDocuments() // Refresh document list
      
    } catch (error) {
      console.error('Batch processing failed:', error)
    }
    
    setIsLoading(false)
  }

  const deleteDocument = async (documentId) => {
    try {
      const response = await fetch(`${API_URL}/api/documents/${documentId}`, {
        method: 'DELETE'
      })

      if (response.ok) {
        loadDocuments()
      }
    } catch (error) {
      console.error('Delete failed:', error)
    }
  }

  return (
    <main className="min-h-screen p-6 bg-gray-50">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="text-center">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">📚 Curatore v2</h1>
          <p className="text-gray-600 text-lg">RAG Document Processing & Optimization</p>
        </header>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* System Status */}
          <div className="lg:col-span-1">
            <HealthCheck 
              apiUrl={API_URL}
              health={health}
              llmConnected={llmConnected}
            />
          </div>

          {/* File Upload */}
          <div className="lg:col-span-2">
            <FileUpload 
              onUpload={handleFileUpload}
              supportedFormats={supportedFormats}
              isLoading={isLoading}
            />
          </div>
        </div>

        {/* Processing Results */}
        <ProcessingResults 
          documents={documents}
          onDelete={deleteDocument}
          onRefresh={loadDocuments}
          apiUrl={API_URL}
          isLoading={isLoading}
        />
      </div>
    </main>
  )
}