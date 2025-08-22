// frontend/app/layout.jsx
import '../styles/globals.css'

export const metadata = {
  title: 'Curatore',
  description: 'The AI-powered data curator',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="bg-gray-50">{children}</body>
    </html>
  )
}