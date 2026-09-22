import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export const metadata: Metadata = {
  title: "jeve",
  description: "A continuously-running simulation of a small interconnected economy.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // One theme, always dark: `.dark` activates the dark: variants inside the
    // shadcn components; the tokens themselves live on :root.
    <html lang="en" className="dark">
      <body>
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster theme="dark" />
      </body>
    </html>
  );
}
