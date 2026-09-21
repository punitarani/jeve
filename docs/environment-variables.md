# Environment Variables

This document describes the environment variables used across the jeve monorepo and their configuration in Doppler.

## Doppler Projects

The monorepo uses three Doppler projects to organize environment variables by deployment target:

### 1. app (Cloudflare Workers - Web App)

**Purpose**: Environment variables for the Next.js web application deployed to Cloudflare Workers.

| Variable | Description | Example |
|----------|-------------|---------|
| `NODE_ENV` | Node environment | `production` |
| `NEXT_PUBLIC_API_URL` | API endpoint URL | `https://jeve-api.punitarani.com` |
| `NEXT_PUBLIC_JEVE_API` | Alternative API URL | `https://jeve-api.punitarani.com` |
| `NEXT_PUBLIC_JEVE_APP` | App URL | `https://jeve.punitarani.com` |
| `NEXT_TELEMETRY_DISABLED` | Disable Next.js telemetry | `1` |

### 2. infra (GitHub Actions CI/CD)

**Purpose**: Environment variables for CI/CD pipelines and deployment automation.

| Variable | Description | Example |
|----------|-------------|---------|
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token | `cfut_...` |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID | `64485cb6...` |
| `CLOUDFLARE_WORKER_NAME` | Worker name | `jeve-web` |
| `FLY_API_TOKEN` | Fly.io API token | `FlyV1 ...` |
| `FLY_APP_NAME` | Fly.io app name | `jeve-backend` |
| `JEVE_DATABASE_URL` | Database URL for CI | `postgresql://...` |
| `DOCKER_REGISTRY` | Docker registry | `docker.io` |
| `MIGRATIONS_DB_URL` | Database for migrations | `postgresql://...` |

### 3. worker (Fly.io - Backend Services)

**Purpose**: Environment variables for backend services (API and simulation worker) deployed to Fly.io.

| Variable | Description | Example |
|----------|-------------|---------|
| `API_HOST` | API bind host | `0.0.0.0` |
| `API_PORT` | API bind port | `8000` |
| `PYTHONPATH` | Python module path | `/app/src` |
| `FLY_APP_NAME` | Fly.io app name | `jeve-backend` |
| `FLY_REGION` | Fly.io region | `iad` |
| `JEVE_DATABASE_URL` | Primary database URL | `postgresql://...` |
| `JEVE_DATABASE_POOLED_URL` | Pooled database URL | `postgresql://...` |
| `JEVE_CORS_ORIGINS` | Allowed CORS origins | `https://jeve.punitarani.com` |
| `JEVE_OPS_DIR` | Operations directory | `/tmp/jeve-ops` |
| `JEVE_POLICY` | Simulation policy | `jev` |
| `JEVE_SIM_POLICY` | Sim policy | `jev` |
| `JEVE_SIM_CALLS` | Call mode | `record` |
| `JEVE_SIM_DAYS` | Simulation days | `35` |
| `JEVE_SIM_DAY_MINUTES` | Sim day minutes | `24` |
| `JEVE_SIM_SPEED` | Simulation speed | `1.0` |
| `JEVE_CALLS` | Call mode | `record` |
| `JEVE_BUDGET_CEILING_USD` | Budget ceiling | `20` |
| `JEVE_BUDGET_EXPLORATION_USD` | Exploration budget | `12` |
| `JEVE_DAILY_BUDGET_USD` | Daily budget | `2.00` |
| `JEVE_RUN_CAP_USD` | Run cap | `100` |
| `OPENROUTER_API_KEY` | OpenRouter API key | `sk-or-v1-...` |
| `OPENROUTER_BASE_URL` | OpenRouter base URL | `https://openrouter.ai/api/v1` |

## Usage

### Local Development

```bash
# Use Doppler for local development
doppler run --project worker --config dev -- make api
doppler run --project app --config dev -- cd apps/web && pnpm dev
```

### Production Deployment

```bash
# Deploy with Doppler secrets
doppler run --project infra --config prd -- make deploy
```

### CI/CD Integration

GitHub Actions uses the `infra` project for deployment credentials:

```yaml
- name: Deploy to Cloudflare Workers
  uses: cloudflare/wrangler-action@v3
  with:
    apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
    accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

## Security Notes

* All sensitive values are stored in Doppler, not in code
* Use different configs for dev/stg/prd environments
* Rotate API keys regularly
* Monitor usage and spending limits
* Use least-privilege access for service accounts

## Adding New Variables

1. Determine which project the variable belongs to
2. Add to the appropriate Doppler config:
   ```bash
   doppler secrets set NEW_VAR=value --project PROJECT --config CONFIG
   ```
3. Update this documentation
4. Test the application with the new variable

## Troubleshooting

### Common Issues

1. **Missing environment variable**
   * Check if the variable exists in the correct Doppler project
   * Verify the config (dev/stg/prd) is correct
   * Ensure the application is using `doppler run`

2. **Permission denied**
   * Verify you have access to the Doppler project
   * Check if the token is valid
   * Ensure the correct scope is being used

3. **Wrong value in production**
   * Check if the variable is set in the `prd` config
   * Verify the deployment is using the correct project
   * Check for typos in variable names
