#!/usr/bin/env node
// A static file server for `next build`'s export (WEB-0005). `make e2e` uses
// it in place of `next start`, which does not exist for `output: "export"`.
// Resolution mirrors both nginx (`try_files $uri $uri/index.html $uri.html`)
// and Workers static assets: a clean URL finds its .html.
//
//   node scripts/static-serve.mjs <directory> --port <port>

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { join, normalize, resolve } from "node:path";

const args = process.argv.slice(2);
const dir = resolve(args[0] ?? "out");
const port = Number(args[args.indexOf("--port") + 1] ?? 3000);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json",
};

/** The first readable file among the candidates, or null. */
async function find(pathname) {
  for (const candidate of [
    pathname,
    `${pathname}/index.html`,
    `${pathname}.html`,
  ]) {
    // `join` keeps a leading slash inside the root; `..` is rejected by the
    // normalize check in the handler, so this cannot escape `dir`.
    const file = join(dir, candidate);
    try {
      if ((await stat(file)).isFile()) return file;
    } catch {
      /* try the next candidate */
    }
  }
  return null;
}

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://x");
  const pathname = normalize(decodeURIComponent(url.pathname));
  if (pathname.startsWith("..")) {
    res.writeHead(403).end();
    return;
  }
  const file =
    (await find(pathname)) ?? (pathname !== "/" ? await find("/404") : null);
  if (!file) {
    res.writeHead(404).end("not found\n");
    return;
  }
  const ext = file.slice(file.lastIndexOf("."));
  res.writeHead(file.endsWith("404.html") ? 404 : 200, {
    "content-type": TYPES[ext] ?? "application/octet-stream",
    // The export fingerprints everything under _next/; the HTML itself must
    // always be revalidated or a redeploy never reaches a cached page.
    "cache-control": file.includes("/_next/")
      ? "public, max-age=31536000, immutable"
      : "no-cache",
  });
  res.end(await readFile(file));
}).listen(port, () => {
  console.log(`serving ${dir} on http://127.0.0.1:${port}`);
});
