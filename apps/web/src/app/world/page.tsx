import type { Metadata } from "next";

import { WorldExplorer } from "@/components/WorldExplorer";

export const metadata: Metadata = { title: "jeve — the world" };

export default function WorldPage() {
  return <WorldExplorer />;
}
