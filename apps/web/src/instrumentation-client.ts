// CORE-0012: the browser's side of the same seam. Next runs this before
// hydration on every page. With no DSN baked in, `Sentry.init` is a no-op and
// no request leaves the page — which is what `make e2e` and the CI build rely
// on. There is no server-side twin: the site is a static export (WEB-0005).
import * as Sentry from "@sentry/nextjs";
import { API } from "@/lib/api";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

Sentry.init({
	dsn,
	environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "development",
	// A static site with a handful of viewers: every trace is affordable, and
	// a page load that never reaches `/state` is the one worth seeing whole.
	tracesSampleRate: 1.0,
	enableLogs: true,
	sendDefaultPii: false,
	integrations: [Sentry.browserTracingIntegration()],
	// `sentry-trace`/`baggage` on a cross-origin GET turn it into a
	// preflighted request, so only once there is a project to connect the
	// trace to. EventSource cannot carry headers, so `/stream` never joins one.
	tracePropagationTargets: dsn ? [API] : [],
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
