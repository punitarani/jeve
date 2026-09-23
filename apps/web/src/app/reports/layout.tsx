import "@/components/report/report.css";

/**
 * Every report page: the report's typefaces and its scoped stylesheet.
 *
 * The rest of the app is set in the system monospace; a report is long-form
 * reading, so it carries the first report's faces — Plex for prose,
 * JetBrains Mono for numbers, Pixelify for headings (WEB-0007). A stylesheet
 * link rather than next/font, for WEB-0006's reason: a font fetched at build
 * time makes every build depend on Google. Here only a reader's first paint
 * does, and it falls back to the system faces.
 */
export default function ReportsLayout({ children }: { children: React.ReactNode }) {
	return (
		<>
			<link rel="preconnect" href="https://fonts.googleapis.com" />
			<link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
			<link
				rel="stylesheet"
				href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;500;700&family=Pixelify+Sans:wght@500;600;700&display=swap"
				precedence="default"
			/>
			<div className="rpt">{children}</div>
		</>
	);
}
