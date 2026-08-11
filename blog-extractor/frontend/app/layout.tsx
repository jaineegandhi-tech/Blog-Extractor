import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Website Blog Extractor",
  description: "Paste a website URL, get every blog post as Excel/CSV.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen text-slate-900">{children}</body>
    </html>
  );
}
