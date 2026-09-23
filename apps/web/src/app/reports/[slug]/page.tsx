import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BODIES } from "@/reports/bodies";
import { findReport, REPORTS } from "@/reports";

// WEB-0005: every published report is a file in the export; an unknown slug
// is a 404, not a render.
export const dynamicParams = false;

export function generateStaticParams() {
	return REPORTS.map((r) => ({ slug: r.slug }));
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
	const report = findReport((await params).slug);
	if (!report) return {};
	return {
		title: `${report.title} · reports`,
		description: `${report.headline}. ${report.summary}`,
		openGraph: { title: `${report.title} · jeve`, description: report.headline },
	};
}

export default async function ReportPage({ params }: Props) {
	const { slug } = await params;
	const Body = BODIES[slug];
	if (!findReport(slug) || !Body) notFound();
	return <Body />;
}
