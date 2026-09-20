// Next's ambient types, referenced from a file we own.
//
// `next-env.d.ts` does the same job, but Next rewrites it on every `dev` and
// `build` to import route types from whichever dist directory ran last
// (`.next/dev` or `.next-e2e`), so tracking it dirties the tree on each e2e
// run. It is gitignored; this keeps `tsc --noEmit` working on a clean clone,
// before any Next command has generated it.

/// <reference types="next" />
/// <reference types="next/image-types/global" />
