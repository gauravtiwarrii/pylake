import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/auth-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: {
    default: "PyLake — Build. Analyze. Innovate.",
    template: "%s | PyLake",
  },
  description:
    "PyLake brings data engineering, lakehouse analytics, SQL, pipelines and optional AI assistance into one open-source platform.",
  applicationName: "PyLake",
  openGraph: {
    title: "PyLake — Build. Analyze. Innovate.",
    description:
      "An AI-powered lakehouse platform for data engineering, analytics and orchestration.",
    siteName: "PyLake",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "PyLake — Build. Analyze. Innovate.",
    description: "AI-Powered Lakehouse Platform.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <AuthProvider>
            <AppShell>{children}</AppShell>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
