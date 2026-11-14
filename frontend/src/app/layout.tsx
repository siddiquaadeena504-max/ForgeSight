import type { Metadata } from "next";
import "./globals.css";
import Shell from "@/components/Shell";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = { title: "ForgeSight – Manufacturing Quality Inspection", description: "Profile-driven visual defect inspection platform" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans">
        <AuthProvider><Shell>{children}</Shell></AuthProvider>
      </body>
    </html>
  );
}
