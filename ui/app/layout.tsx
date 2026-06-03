import type { Metadata } from 'next'
import { DM_Serif_Display, DM_Sans, DM_Mono } from 'next/font/google'
import './globals.css'

const dmSerifDisplay = DM_Serif_Display({
  subsets: ['latin'],
  weight: '400',
  variable: '--font-dm-serif',
})

const dmSans = DM_Sans({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-dm-sans',
})

const dmMono = DM_Mono({
  subsets: ['latin'],
  weight: ['300', '400', '500'],
  variable: '--font-dm-mono',
})

export const metadata: Metadata = {
  title: 'Robinhood Velocity Signal Engine',
  description:
    "Prediction market velocity signals mapped to equity positions via Robinhood's agentic trading MCP",
  openGraph: {
    title: 'Robinhood Velocity Signal Engine',
    description:
      "Prediction market velocity signals mapped to equity positions via Robinhood's agentic trading MCP",
    type: 'website',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${dmSerifDisplay.variable} ${dmSans.variable} ${dmMono.variable}`}
    >
      <body>{children}</body>
    </html>
  )
}
