"use client";

import { mountWorld, type WorldStatus } from "@jeve/world";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { API } from "@/lib/api";

/**
 * The landing-page hero: the town, running, with no controls.
 *
 * It subscribes to the same `seq` stream as everything else, so what moves here
 * is the simulation and not an animation of it. When nothing new has happened
 * for a few seconds — the daemon is paused, it is sim-night, a fixture has
 * reached its horizon — it replays the last sim-hour of *recorded* movement and
 * says that it is doing so.
 */
export function WorldHero() {
  const container = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<WorldStatus | null>(null);

  useEffect(() => {
    if (container.current === null) return;
    let last = 0;
    // A fresh canvas per mount: Strict Mode mounts twice in development, and a
    // WebGL context cannot be shared across the two.
    const handle = mountWorld(container.current, {
      api: API,
      mode: "hero",
      debug: process.env.NODE_ENV !== "production",
      onStatus: (next) => {
        const now = performance.now();
        if (now - last > 400) {
          last = now;
          setStatus(next);
        }
      },
    });
    return () => handle.dispose();
  }, []);

  return (
    <section className="hero" data-testid="world-hero">
      <div ref={container} className="hero-canvas" />
      <div className="hero-caption">
        <div>
          <b>jeve</b>{" "}
          <span className="muted">
            four firms, one town, every decision a typed question
          </span>
        </div>
        <div className="hero-meta">
          <span data-testid="hero-clock">{status?.label ?? "…"}</span>
          <span className="muted">
            seq <span data-testid="hero-seq">{status?.seq ?? 0}</span>
          </span>
          <span className="muted">
            {status?.visible ?? 0} out · {status?.walking ?? 0} walking
          </span>
          {status?.live ? (
            <span className="pill good" data-testid="hero-live">
              live
            </span>
          ) : (
            <span className="pill" data-testid="hero-replaying">
              {status?.replaying ? "quiet — replaying the last hour" : "connecting"}
            </span>
          )}
          <Link href="/world" className="hero-link" data-testid="open-world">
            open the world →
          </Link>
        </div>
      </div>
    </section>
  );
}
