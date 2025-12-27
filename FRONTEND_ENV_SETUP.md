# Frontend Environment Configuration

RAGBrain frontend uses Vite, which requires environment variables to have a `VITE_` prefix to be exposed to the browser.

## File Structure

```
ragbrain/
├── .env                    # Backend config
├── .env.example            # Backend template
├── .env.frontend           # Frontend template
│
└── frontend/
    ├── .env.local          # Local dev (gitignored)
    └── .env.production     # Production (gitignored)
```

## Why Separate Frontend Config?

Vite only exposes variables with the `VITE_` prefix to the browser for security.

- **Root `.env`**: Backend variables (API keys, database URLs)
- **Frontend `.env.local`**: Frontend variables with `VITE_` prefix

## Local Development Setup

Copy the template and configure for local dev:

```bash
cp .env.frontend frontend/.env.local
```

Edit `frontend/.env.local`:

```bash
VITE_AUTH_PROVIDER=none
VITE_API_URL=http://localhost:8000
```

Start the dev server:

```bash
cd frontend
npm run dev
```

## Production Deployment

For production with AWS Cognito:

```bash
# frontend/.env.production
VITE_AUTH_PROVIDER=cognito
VITE_API_URL=https://xxxxx.execute-api.REGION.amazonaws.com
VITE_AWS_REGION=us-east-1
VITE_COGNITO_USER_POOL_ID=REGION_XXXXX
VITE_COGNITO_CLIENT_ID=your-client-id
VITE_COGNITO_DOMAIN=your-domain.auth.REGION.amazoncognito.com
VITE_COGNITO_REDIRECT_URI=https://your-domain.com
```

## Available Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_AUTH_PROVIDER` | Authentication method | `none`, `cognito`, `oauth` |
| `VITE_API_URL` | Backend API endpoint | `http://localhost:8000` |
| `VITE_AWS_REGION` | AWS region | `us-east-1` |
| `VITE_COGNITO_USER_POOL_ID` | Cognito user pool | `REGION_XXXXX` |
| `VITE_COGNITO_CLIENT_ID` | Cognito app client | `your-client-id` |
| `VITE_COGNITO_DOMAIN` | Cognito domain | `domain.auth.REGION.amazoncognito.com` |
| `VITE_COGNITO_REDIRECT_URI` | OAuth redirect | `https://your-domain.com` |

## Important

1. Never commit `.env.local` or `.env.production` (gitignored)
2. No secrets in `VITE_` variables (exposed to browser)
3. Use `.env.frontend` as template

## Dev Server Proxy

The Vite dev server proxies API requests to the backend. In `vite.config.js`:

```javascript
server: {
  proxy: {
    '/api': {
      target: process.env.VITE_API_URL || 'http://localhost:8000',
      changeOrigin: true,
    }
  }
}
```

This handles CORS during development.
