import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono-face", display: "swap" });

export const metadata: Metadata = {
  title: {
    default: "Sentinel — model-serving gateway & observability plane",
    template: "%s · Sentinel",
  },
  description:
    "An OpenAI-compatible gateway that routes every prompt to the cheapest capable model, accounts for tokens and cost per request, traces the whole path, and survives upstream failures.",
  keywords: [
    "LLM gateway",
    "model serving",
    "OpenTelemetry",
    "token accounting",
    "cost optimisation",
    "circuit breaker",
    "Prometheus",
    "FastAPI",
    "Next.js",
  ],
  authors: [{ name: "Shahriar Ahmed Seam" }],
  openGraph: {
    title: "Sentinel — model-serving gateway & observability plane",
    description:
      "Route to the cheapest capable model, account for every token, trace every hop, and keep serving when an upstream fails.",
    type: "website",
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#06070a",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
