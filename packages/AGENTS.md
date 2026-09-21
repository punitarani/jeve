# Shared Packages Standards

Shared packages provide common functionality used across the monorepo. These packages maintain strict typing and validation standards.

## Packages

### @jeve/contracts
- **Purpose**: Zod schemas for all API I/O boundaries
- **Dependencies**: zod ^4.0.0
- **Usage**: Imported by both Python (via generated types) and web applications

### @jeve/world
- **Purpose**: GL-free scene model for voxel town rendering
- **Dependencies**: three 0.186.0, @jeve/contracts, zod ^4.0.0
- **Usage**: Used by web application for 3D visualization
- **Key Feature**: Separates scene model from rendering logic

## Standards

- **TypeScript**: Strict mode for all packages
- **Module System**: ES modules (`"type": "module"`)
- **Entry Points**: Both `main` and `types` point to `./src/index.ts`
- **Validation**: Zod schemas at all boundaries
- **Workspace**: Uses pnpm workspace protocol (`workspace:*`)

## Package Management

- **Manager**: pnpm with workspace support
- **Private**: All packages are marked as private (not published to npm)
- **Versioning**: Consistent 0.1.0 base version across packages
- **Peer Dependencies**: Managed through workspace protocol

## Common Commands

```bash
# Build all packages
pnpm --filter "./packages/**" build

# Type check all packages
pnpm --filter "./packages/**" tsc --noEmit

# Add dependency to specific package
pnpm --filter @jeve/contracts add zod
```

## Key Constraints

- No external I/O in shared packages
- All types must be exported from index.ts
- Zod schemas should be comprehensive and cover edge cases
- Three.js usage in @jeve/world is isolated to rendering only