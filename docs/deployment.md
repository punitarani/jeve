# Deployment

This document describes how to deploy the jeve monorepo applications using modern cloud platforms.

## Architecture

The system consists of four main components deployed across different platforms:

1. **Web** (`apps/web/`) - Next.js frontend → **Cloudflare Workers**
2. **API** (`apps/api/`) - FastAPI backend → **Fly.io**
3. **Sim** (`apps/sim/`) - Simulation worker → **Fly.io**
4. **Database** - PostgreSQL → **Fly.io Postgres** or external provider

## Platform Choices

### Cloudflare Workers (Web)

* **Why**: Global CDN, edge computing, excellent Next.js support
* **Benefits**: Zero cold starts, automatic scaling, DDoS protection
* **Deployment**: `wrangler deploy`

### Fly.io (Backend Services)

* **Why**: Simple deployment, good pricing, global regions, persistent storage
* **Benefits**: Easy Postgres integration, process groups, health checks
* **Deployment**: `fly deploy`

## Environment Configuration

### Local Development

```bash
# Copy appropriate env file
cp .env.app.example .env.local      # For web development
cp .env.worker.example .env         # For backend development

# Start dependencies
make db-up

# Run services
make api      # Terminal 1 - API server
make sim      # Terminal 2 - Simulation worker
cd apps/web && pnpm dev  # Terminal 3 - Web development server
```

### Production Deployment

#### Web App (Cloudflare Workers)

```bash
# Install Wrangler CLI
npm install -g wrangler

# Login to Cloudflare
wrangler login

# Deploy web app
make deploy-web
# or: cd apps/web && wrangler deploy
```

#### Backend Services (Fly.io)

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login to Fly.io
fly auth login

# Launch app (first time only)
fly launch --config fly.toml

# Deploy API
make deploy-api
# or: fly deploy --config fly.toml

# Deploy simulation worker
make deploy-sim
# or: fly deploy --config fly.toml --process-group sim
```

## Environment Variables

### Web App (.env.app.example)

```bash
# API endpoint
NEXT_PUBLIC_API_URL=https://api.jeve.app

# Cloudflare deployment
CLOUDFLARE_API_TOKEN=your-cloudflare-api-token
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_WORKER_NAME=jeve-web
```

### Backend Services (.env.worker.example)

```bash
# Database connection
JEVE_DATABASE_URL=postgresql://jeve:jeve@jeve-db.internal:5432/jeve

# API configuration
API_HOST=0.0.0.0
API_PORT=8000

# Simulation configuration
JEVE_SIM_POLICY=jev|rules
JEVE_SIM_CALLS=replay|record
JEVE_BUDGET_CEILING_USD=20.0

# Fly.io deployment
FLY_API_TOKEN=your-fly-api-token
FLY_APP_NAME=jeve-backend
FLY_REGION=sjc
```

### Infrastructure (.env.infra.example)

```bash
# Database for CI/CD
JEVE_DATABASE_URL=postgresql://jeve:jeve@localhost:5432/jeve

# Deployment credentials
CLOUDFLARE_API_TOKEN=your-cloudflare-api-token
FLY_API_TOKEN=your-fly-api-token

# Monitoring
SENTRY_DSN=your-sentry-dsn
```

## Database Setup

### Fly.io Postgres

```bash
# Create Postgres cluster
fly postgres create --name jeve-db

# Attach to app
fly postgres attach jeve-db --app jeve-backend

# Get connection string
fly postgres connect jeve-db
```

### External Database

```bash
# Set database URL
fly secrets set JEVE_DATABASE_URL=postgresql://user:pass@host:port/db
```

## Secrets Management

### Cloudflare Workers

```bash
# Set secrets
wrangler secret put CLOUDFLARE_API_TOKEN
wrangler secret put NEXT_PUBLIC_ANALYTICS_ID
```

### Fly.io

```bash
# Set secrets
fly secrets set OPENROUTER_API_KEY=your-key
fly secrets set JEVE_DATABASE_URL=your-db-url
```

## Health Checks

### Web App (Cloudflare)

* Automatic health checks via Cloudflare's edge network
* Custom health check endpoint: `/api/health`

### API Service (Fly.io)

* HTTP health check: `GET /health`
* TCP health check on port 8000
* Automatic restart on failure

### Simulation Worker (Fly.io)

* Process monitoring via Fly.io
* Automatic restart on failure
* Health via writer lock status

## Monitoring

### Cloudflare Workers

* Built-in analytics and logging
* Real User Monitoring (RUM)
* Performance metrics

### Fly.io

* Application metrics and logging
* Database metrics
* Custom health checks

## Scaling

### Web App (Cloudflare)

* Automatic scaling to zero
* Global edge deployment
* No cold starts for static content

### Backend Services (Fly.io)

* Horizontal scaling: `fly scale count`
* Vertical scaling: `fly scale vm`
* Auto-scaling based on metrics

## CI/CD Integration

### GitHub Actions

```yaml
# Deploy web app
- name: Deploy to Cloudflare Workers
  uses: cloudflare/wrangler-action@v3
  with:
    apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
    workingDirectory: apps/web

# Deploy backend
- name: Deploy to Fly.io
  uses: superfly/flyctl-actions/setup-flyctl@master
  env:
    FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
  run: fly deploy --config fly.toml
```

## Cost Optimization

### Cloudflare Workers

* Pay per request (very cost-effective for web)
* Free tier available for low traffic

### Fly.io

* Pay per VM hour
* Auto-stop machines when idle
* Shared CPU for development

## Security

### Cloudflare Workers

* DDoS protection built-in
* Web Application Firewall (WAF)
* Automatic HTTPS

### Fly.io

* Private networking between services
* WireGuard encryption
* Secrets management

## Backup and Recovery

### Database

```bash
# Fly.io Postgres backup
fly postgres backup jeve-db

# Manual backup
fly ssh console -C "pg_dump $DATABASE_URL" > backup.sql
```

### Application State

* Stateless web app (Cloudflare handles state)
* Simulation state in Postgres (persistent volumes)
* Configuration via environment variables

## Troubleshooting

### Common Issues

1. **API not accessible**
   * Check Fly.io status: `fly status`
   * View logs: `fly logs`
   * Check health: `fly checks`

2. **Web app not updating**
   * Check Cloudflare deployment: `wrangler deployments list`
   * Clear cache: `wrangler kv:key delete --binding=ASSETS`

3. **Database connection issues**
   * Verify `JEVE_DATABASE_URL` is set correctly
   * Check Fly.io Postgres status
   * Test connectivity: `fly ssh console`

### Debug Commands

```bash
# Fly.io debugging
fly ssh console
fly logs --app jeve-backend
fly status --app jeve-backend

# Cloudflare debugging
wrangler tail
wrangler dev --local
```

## Migration from Docker

The current setup supports both Docker and cloud-native deployment:

* **Local development**: Use `make docker-up` for local testing
* **Production**: Use Cloudflare Workers + Fly.io for better performance and cost
* **Hybrid**: Run database locally, deploy apps to cloud

This approach provides:

* Better performance (edge computing)
* Lower costs (pay-per-use)
* Easier scaling (managed services)
* Better developer experience (simple deployment)
