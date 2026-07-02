import type { Metadata } from "next";
import "./globals.css";
import "highlight.js/styles/atom-one-dark.css";
import { TopBar } from "@/components/TopBar";
import { FloatingAssistant } from "@/components/FloatingAssistant";
import { AlertBanner } from "@/components/AlertBanner";

export const metadata: Metadata = {
  title: "BOILER-AI — Realtime Dashboard",
  description: "Realtime boiler + chimney monitoring with agentic RAG assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <TopBar />
        <AlertBanner />
        <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
        <FloatingAssistant />
      </body>
    </html>
  );
}
