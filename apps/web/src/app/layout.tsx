import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

const DESCRIPTION =
  "A continuously-running simulation of a small interconnected economy — twelve firms in one district, every decision a typed question.";

export const metadata: Metadata = {
  metadataBase: new URL("https://jeve.punitarani.com"),
  title: { default: "jeve", template: "%s · jeve" },
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: "jeve",
    url: "/",
    title: "jeve",
    description: DESCRIPTION,
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "The district of jeve rendered in voxels — twelve firms, teams as floors.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "jeve",
    description: DESCRIPTION,
    images: ["/og.png"],
  },
};

export const viewport = { themeColor: "#0e1116" };

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
