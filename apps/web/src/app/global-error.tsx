"use client";

// CORE-0012: the last React error boundary. It replaces the root layout when
// it fires, so it renders <html> and <body> itself. Anything caught here has
// already broken the page; saying so, to the viewer and to Sentry, is the job.
import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";
import "./globals.css";

export default function GlobalError({
	error,
	reset,
}: {
	error: Error & { digest?: string };
	reset: () => void;
}) {
	useEffect(() => {
		Sentry.captureException(error);
	}, [error]);

	return (
		<html lang="en" className="dark">
			<body>
				<main className="mx-auto max-w-xl p-8">
					<h1 className="text-lg font-semibold">Something broke on this page.</h1>
					<p className="mt-2 text-sm opacity-70">{error.message}</p>
					<button type="button" className="mt-4 underline" onClick={reset}>
						Try again
					</button>
				</main>
			</body>
		</html>
	);
}
