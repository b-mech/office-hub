import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Office Hub",
  description: "Document review and promotion workspace for Office Hub.",
  icons: {
    icon: "/favicon.png",
    shortcut: "/favicon.png",
    apple: "/favicon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="theme-monocle min-h-full bg-[#0f1117] text-white">
        <div className="flex min-h-screen">
          <aside className="hidden w-56 shrink-0 border-r border-white/10 bg-[#11141b] px-4 py-5 lg:block">
            <Link href="/documents" className="flex items-center gap-2">
              <img src="/favicon.png" alt="Office Hub" className="h-6 w-6" />
              <span className="text-sm font-semibold text-white">Office Hub</span>
            </Link>
            <nav className="mt-8 flex flex-col gap-1">
              <Link
                href="/documents"
                className="rounded-lg px-3 py-2 text-sm text-white/60 transition hover:bg-white/5 hover:text-white"
              >
                Documents
              </Link>
              <Link
                href="/lots"
                className="rounded-lg px-3 py-2 text-sm text-white/60 transition hover:bg-white/5 hover:text-white"
              >
                Lots
              </Link>
              <Link
                href="/costbook"
                className="rounded-lg px-3 py-2 text-sm text-white/60 transition hover:bg-white/5 hover:text-white"
              >
                Costbook
              </Link>
            </nav>
          </aside>
          <div className="min-w-0 flex-1">{children}</div>
        </div>
      </body>
    </html>
  );
}
