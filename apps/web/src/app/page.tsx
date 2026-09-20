import { Dashboard } from "@/components/Dashboard";
import { fetchEvents, fetchState } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Page() {
  try {
    const state = await fetchState();
    const page = await fetchEvents(0, 400);
    return <Dashboard initialState={state} initialEvents={page.events} />;
  } catch (error) {
    return (
      <main style={{ padding: 32 }}>
        <h1>jeve</h1>
        <p className="muted">The API is not reachable.</p>
        <pre className="panel" style={{ whiteSpace: "pre-wrap" }}>
          {error instanceof Error ? error.message : String(error)}
        </pre>
        <p className="muted">
          Start it with <code>make api</code>, and the world with{" "}
          <code>make fixture</code>.
        </p>
      </main>
    );
  }
}
