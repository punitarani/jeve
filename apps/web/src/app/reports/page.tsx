import type { Metadata } from "next";
import { LiveReport } from "@/components/report/LiveReport";

export const metadata: Metadata = {
	title: "reports",
	description:
		"The field report, live: what the town's typed decisions add up to so far — the books, the people, the model, the outages — and every report published from it.",
};

// WEB-0005: a static shell; the report is fetched in the browser.
export default function ReportsPage() {
	return <LiveReport />;
}
