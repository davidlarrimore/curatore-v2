'use client'

import React, { useState, useEffect } from 'react'
import { Loader2, AlertCircle } from 'lucide-react'
import { Document, Page, pdfjs } from 'react-pdf'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import * as mammoth from 'mammoth'
import * as XLSX from 'xlsx'
import Papa from 'papaparse'

// Import react-pdf styles
import 'react-pdf/dist/esm/Page/AnnotationLayer.css'
import 'react-pdf/dist/esm/Page/TextLayer.css'

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

interface FilePreviewProps {
  blob: Blob
  filename: string
  contentType: string | null
}

export default function FilePreview({ blob, filename, contentType }: FilePreviewProps) {
  const [content, setContent] = useState<string | null>(null)
  const [htmlContent, setHtmlContent] = useState<string | null>(null)
  const [markdownContent, setMarkdownContent] = useState<string | null>(null)
  const [tableData, setTableData] = useState<{ headers: string[]; rows: string[][] } | null>(null)
  const [numPages, setNumPages] = useState<number>(0)
  const [pageNumber, setPageNumber] = useState<number>(1)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fileType, setFileType] = useState<string>('')

  useEffect(() => {
    loadPreview()
  }, [blob, filename])

  const loadPreview = async () => {
    setIsLoading(true)
    setError(null)
    setContent(null)
    setHtmlContent(null)
    setMarkdownContent(null)
    setTableData(null)

    try {
      const extension = filename.split('.').pop()?.toLowerCase() || ''
      setFileType(extension)

      // Markdown files (render as formatted markdown)
      if (['md', 'markdown'].includes(extension)) {
        const text = await blob.text()
        setMarkdownContent(text)
      }
      // Plain text files (show as code)
      else if (['txt', 'log'].includes(extension)) {
        const text = await blob.text()
        setContent(text)
      }
      // JSON files
      else if (['json'].includes(extension)) {
        const text = await blob.text()
        try {
          const parsed = JSON.parse(text)
          setContent(JSON.stringify(parsed, null, 2))
        } catch {
          setContent(text)
        }
      }
      // Code files
      else if (['js', 'jsx', 'ts', 'tsx', 'py', 'java', 'cpp', 'c', 'h', 'css', 'html', 'xml', 'yaml', 'yml', 'sql', 'sh', 'bash'].includes(extension)) {
        const text = await blob.text()
        setContent(text)
      }
      // CSV files
      else if (['csv', 'tsv'].includes(extension)) {
        const text = await blob.text()
        const parsed = Papa.parse(text, {
          header: false,
          skipEmptyLines: true,
        })

        if (parsed.data && parsed.data.length > 0) {
          const headers = (parsed.data[0] as string[]) || []
          const rows = parsed.data.slice(1) as string[][]
          setTableData({ headers, rows: rows.slice(0, 100) }) // Limit to first 100 rows
        } else {
          setError('No data found in CSV file')
        }
      }
      // Excel files
      else if (['xlsx', 'xls'].includes(extension)) {
        const arrayBuffer = await blob.arrayBuffer()
        const workbook = XLSX.read(arrayBuffer, { type: 'array' })
        const firstSheetName = workbook.SheetNames[0]
        const worksheet = workbook.Sheets[firstSheetName]
        const jsonData = XLSX.utils.sheet_to_json(worksheet, { header: 1 }) as string[][]

        if (jsonData.length > 0) {
          const headers = jsonData[0] || []
          const rows = jsonData.slice(1, 101) // Limit to first 100 rows
          setTableData({ headers, rows })
        } else {
          setError('No data found in Excel file')
        }
      }
      // Word documents
      else if (['docx'].includes(extension)) {
        const arrayBuffer = await blob.arrayBuffer()
        const result = await mammoth.convertToHtml({ arrayBuffer })
        setHtmlContent(result.value)

        if (result.messages.length > 0) {
          console.warn('Mammoth conversion warnings:', result.messages)
        }
      }
      // PDF files
      else if (['pdf'].includes(extension)) {
        // PDF will be handled by react-pdf component
        setContent('PDF')
      }
      // Images
      else if (['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'bmp'].includes(extension)) {
        const reader = new FileReader()
        reader.onload = () => {
          setContent(reader.result as string)
        }
        reader.readAsDataURL(blob)
      }
      else {
        setError(`Preview not supported for .${extension} files`)
      }
    } catch (err: unknown) {
      console.error('Preview error:', err)
      setError(err instanceof Error ? err.message : 'Failed to load preview')
    } finally {
      setIsLoading(false)
    }
  }

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setPageNumber(1)
    setIsLoading(false)
  }

  const onDocumentLoadError = (error: Error) => {
    console.error('PDF load error:', error)
    setError('Failed to load PDF')
    setIsLoading(false)
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mb-4" />
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading preview...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <div className="w-16 h-16 rounded-2xl bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center mb-4">
          <AlertCircle className="w-8 h-8 text-amber-600 dark:text-amber-400" />
        </div>
        <p className="text-sm font-medium text-amber-800 dark:text-amber-200 mb-2">Preview Not Available</p>
        <p className="text-sm text-gray-600 dark:text-gray-400 text-center max-w-md">{error}</p>
      </div>
    )
  }

  // Render PDF
  if (fileType === 'pdf' && content === 'PDF') {
    return (
      <div className="flex flex-col items-center">
        <Document
          file={blob}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onDocumentLoadError}
          loading={
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mb-4" />
              <p className="text-sm text-gray-500 dark:text-gray-400">Loading PDF...</p>
            </div>
          }
        >
          <Page
            pageNumber={pageNumber}
            renderTextLayer={false}
            renderAnnotationLayer={false}
            className="shadow-lg"
            width={Math.min(800, window.innerWidth - 100)}
          />
        </Document>

        {numPages > 1 && (
          <div className="flex items-center gap-4 mt-6 bg-gray-100 dark:bg-gray-800 px-4 py-2 rounded-lg">
            <button
              onClick={() => setPageNumber(page => Math.max(1, page - 1))}
              disabled={pageNumber <= 1}
              className="px-3 py-1 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="text-sm text-gray-700 dark:text-gray-300">
              Page {pageNumber} of {numPages}
            </span>
            <button
              onClick={() => setPageNumber(page => Math.min(numPages, page + 1))}
              disabled={pageNumber >= numPages}
              className="px-3 py-1 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        )}
      </div>
    )
  }

  // Render HTML (Word documents)
  if (htmlContent) {
    return (
      <div
        className="prose prose-sm dark:prose-invert max-w-none p-6 bg-white dark:bg-gray-900 rounded-lg"
        dangerouslySetInnerHTML={{ __html: htmlContent }}
      />
    )
  }

  // Render Markdown
  if (markdownContent) {
    return (
      <div className="prose prose-sm dark:prose-invert max-w-none p-6 bg-white dark:bg-gray-900 rounded-lg overflow-auto max-h-[70vh]">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // Customize code blocks
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            code({ node, inline, className, children, ...props }: any) {
              return inline ? (
                <code className="bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-sm" {...props}>
                  {children}
                </code>
              ) : (
                <code className="block bg-gray-100 dark:bg-gray-800 p-3 rounded-lg overflow-x-auto" {...props}>
                  {children}
                </code>
              )
            },
            // Customize links to open in new tab
            a({ node, children, href, ...props }) {
              return (
                <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                  {children}
                </a>
              )
            },
            // Customize tables for better styling
            table({ node, children, ...props }) {
              return (
                <div className="overflow-x-auto my-4">
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700" {...props}>
                    {children}
                  </table>
                </div>
              )
            },
            th({ node, children, ...props }) {
              return (
                <th className="px-4 py-2 bg-gray-50 dark:bg-gray-800 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider" {...props}>
                  {children}
                </th>
              )
            },
            td({ node, children, ...props }) {
              return (
                <td className="px-4 py-2 text-sm text-gray-900 dark:text-gray-100" {...props}>
                  {children}
                </td>
              )
            },
          }}
        >
          {markdownContent}
        </ReactMarkdown>
      </div>
    )
  }

  // Render tables (CSV, Excel)
  if (tableData) {
    return (
      <div className="overflow-y-auto max-h-[600px]">
        <table className="w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm table-fixed">
          <thead className="bg-gray-50 dark:bg-gray-800 sticky top-0">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase w-12">#</th>
              {tableData.headers.map((header, i) => (
                <th key={i} className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase break-words">
                  {header || `Column ${i + 1}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
            {tableData.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                <td className="px-3 py-2 text-gray-500 dark:text-gray-400 font-mono text-xs align-top">{rowIndex + 1}</td>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="px-3 py-2 text-gray-900 dark:text-gray-100 break-words align-top">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {tableData.rows.length >= 100 && (
          <div className="p-4 bg-amber-50 dark:bg-amber-900/20 border-t border-amber-200 dark:border-amber-800">
            <p className="text-sm text-amber-700 dark:text-amber-300">
              Showing first 100 rows. Download the file to view all data.
            </p>
          </div>
        )}
      </div>
    )
  }

  // Render images
  if (content && content.startsWith('data:image/')) {
    return (
      <div className="flex items-center justify-center p-4">
        <img
          src={content}
          alt={filename}
          className="max-w-full max-h-[70vh] object-contain rounded-lg shadow-lg"
        />
      </div>
    )
  }

  // Render text/code
  if (content) {
    return (
      <pre className="text-sm text-gray-800 dark:text-gray-200 bg-gray-50 dark:bg-gray-900 p-4 rounded-lg overflow-auto max-h-[70vh] whitespace-pre-wrap break-words font-mono">
        {content}
      </pre>
    )
  }

  return null
}
