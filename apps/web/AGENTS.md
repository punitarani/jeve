# Web Development Standards

The web application follows strict TypeScript and React conventions for consistency and type safety.

## Standards

- **Framework**: Next.js 16.3.5 with App Router
- **Language**: TypeScript strict mode (no `any`)
- **Type Patterns**: Discriminated unions over optional-field soup
- **Validation**: Zod at every I/O boundary
- **React**: React 19.2.0 with functional components
- **Testing**: Playwright for end-to-end testing

## Project Structure

```
apps/web/
├── src/
│   ├── app/          # Next.js App Router pages and layouts
│   ├── components/   # Reusable React components
│   └── lib/          # Utility functions and API clients
├── decisions/        # Web-specific architecture decisions
└── e2e/             # Playwright end-to-end tests
```

## TypeScript Conventions

- **Strict Mode**: Always use TypeScript strict mode
- **No Any**: Never use `any` type - use proper typing or `unknown`
- **Discriminated Unions**: Prefer discriminated unions over optional fields
- **Zod Integration**: Use Zod schemas at all I/O boundaries (API, forms, external data)

## Component Patterns

- **Functional Components**: Use functional components with hooks
- **Type Props**: Define explicit interfaces for component props
- **Shared Contracts**: Import shared types from `@jeve/contracts` workspace package
- **World Package**: Use `@jeve/world` for 3D voxel town rendering

## Common Commands

```bash
# Development server
pnpm --filter @jeve/web dev

# Build for production
pnpm --filter @jeve/web build

# Start production server
pnpm --filter @jeve/web start

# Run end-to-end tests
pnpm --filter @jeve/web test:e2e
```

## Key Constraints

- All API calls use typed contracts from `@jeve/contracts`
- World rendering uses the GL-free scene model from `@jeve/world`
- No inline styles - use CSS modules or Tailwind if configured
- Components should be small and focused on single responsibility