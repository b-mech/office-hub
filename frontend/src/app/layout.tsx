import type { Metadata } from "next";
import AppSidebar from "./AppSidebar";
import MobileNavigation from "./MobileNavigation";
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
      <body className="theme-monocle min-h-full bg-[var(--ch-page-bg)] text-[var(--ch-text-primary)]">
        <div className="flex min-h-screen">
          <AppSidebar fallbackUserName={USER_NAME} />
          <div className="min-w-0 flex-1">
            <MobileNavigation />
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
