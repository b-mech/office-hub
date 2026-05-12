import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import { Cog } from "lucide-react";
import "./globals.css";

const USER_NAME = process.env.USER_NAME || "Nicholas";

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
          <aside className="hidden w-56 shrink-0 flex-col border-r border-white/10 bg-[#11141b] px-4 py-5 lg:flex">
            <Link href="/documents" className="flex items-center gap-2">
              <Image src="/favicon.png" alt="Office Hub" width={24} height={24} />
              <span className="text-sm font-semibold text-white">Office Hub</span>
            </Link>
            <nav className="mt-8 flex flex-1 flex-col gap-1">
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
                href="/projects"
                className="rounded-lg px-3 py-2 text-sm text-white/60 transition hover:bg-white/5 hover:text-white"
              >
                Projects
              </Link>
              <Link
                href="/projects/change-orders"
                className="ml-3 rounded-lg border-l border-white/10 px-3 py-1.5 text-xs text-white/45 transition hover:bg-white/5 hover:text-white"
              >
                Change Orders
              </Link>
              <Link
                href="/costbook"
                className="rounded-lg px-3 py-2 text-sm text-white/60 transition hover:bg-white/5 hover:text-white"
              >
                Costbook
              </Link>
            </nav>
            <div className="border-t border-white/10 pt-3">
              <Link
                href="/settings"
                className="flex items-center gap-3 rounded-lg px-2 py-2 text-white/65 transition hover:bg-white/5 hover:text-white"
              >
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#FAC775] text-xs font-bold text-[#0f1117]">
                  {USER_NAME.slice(0, 1).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{USER_NAME}</span>
                <Cog size={15} strokeWidth={2} aria-hidden="true" />
              </Link>
            </div>
          </aside>
          <div className="min-w-0 flex-1">{children}</div>
        </div>
      </body>
    </html>
  );
}
