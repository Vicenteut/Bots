import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import StatusIndicator from "@/components/StatusIndicator";

export const metadata: Metadata = {
  title: "Mission Control",
  description: "Dashboard for armandito + sol-bot",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased dark">
      <body className="min-h-full bg-[#0a0a0a] text-neutral-200 font-mono">
        <Sidebar />
        <div className="md:ml-56">
          <header className="sticky top-0 z-30 flex items-center justify-between px-6 py-3 border-b border-neutral-800 bg-[#0a0a0a]/80 backdrop-blur-sm">
            <span className="text-xs text-neutral-500 uppercase tracking-wider">Mission Control</span>
            <StatusIndicator />
          </header>
          <main className="p-6 pb-24 md:pb-6">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
