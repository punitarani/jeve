import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "jeve",
  description: "A continuously-running simulation of a small interconnected economy.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
