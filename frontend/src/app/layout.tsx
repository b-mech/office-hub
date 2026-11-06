import type { Metadata } from "next";
import AuthGate from "./AuthGate";
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
        <AuthGate fallbackUserName={USER_NAME}>{children}</AuthGate>
      </body>
    </html>
  );
}
