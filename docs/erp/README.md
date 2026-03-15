# Singularity ERP — Enterprise Resource Platform

> The operational interface for Singularity. Not just a dashboard — a fully autonomous native AI platform.

## Overview

Singularity ERP is the web-based control plane for the Singularity Autonomous Enterprise Runtime. It provides real-time enterprise management with an integrated AI chat interface that connects directly to Singularity's agent loop.

**Stack:**
- **Backend:** Fastify + Prisma + PostgreSQL (TypeScript)
- **Frontend:** React 18 + Vite + Zustand + Radix UI (TypeScript)
- **AI Integration:** Direct proxy to Singularity HTTP API (:8450)
- **Auth:** JWT with bcrypt, role-based access control

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Studio (React + Vite)          :3100/dashboard     │
│  ├── Dashboard        — KPIs, revenue, pipeline     │
│  ├── Singularity AI   — Chat with Singularity ⚡    │
│  ├── CRM              — Contacts, Deals, Campaigns  │
│  ├── HRM              — Employees, Departments      │
│  ├── Finance          — Invoices, Revenue, Expenses  │
│  ├── Development      — Projects, Repos, Sprints    │
│  ├── Analytics        — Reports, Metrics            │
│  ├── Security         — Audit Logs, Access Control  │
│  ├── Infrastructure   — Services, Health Monitoring │
│  ├── Integrations     — Third-party Connections     │
│  ├── Workflows        — Automation Pipelines        │
│  ├── Stakeholders     — Investor & Board Management │
│  └── Admin            — Users, Roles, Settings      │
├─────────────────────────────────────────────────────┤
│  Backend (Fastify)              :3100/api           │
│  ├── /api/auth/*      — Register, Login, JWT        │
│  ├── /api/ai/*        — Singularity Chat Proxy      │
│  ├── /api/contacts/*  — CRM Contacts CRUD           │
│  ├── /api/deals/*     — CRM Deals Pipeline          │
│  ├── /api/employees/* — HRM Employee Management     │
│  ├── /api/invoices/*  — Finance Invoicing            │
│  ├── /api/projects/*  — Project Management          │
│  ├── /api/activities/*— Activity Feed               │
│  └── /api/health      — Health Check                │
├─────────────────────────────────────────────────────┤
│  Singularity Runtime            :8450               │
│  └── /api/v1/chat     — Agent Loop (28 tools)       │
├─────────────────────────────────────────────────────┤
│  PostgreSQL                     :5432               │
│  └── artifact_erp DB  — 8 tables (Prisma ORM)      │
└─────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
- Node.js 18+
- PostgreSQL 14+
- Singularity runtime running on :8450

### Setup

```bash
# Backend
cd erp/backend
cp .env.example .env  # Edit with your secrets
npm install
npx prisma db push
npx tsx prisma/seed.ts
npm run dev

# Studio
cd erp/studio/app
npm install
npm run dev
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `JWT_SECRET` | ✅ | JWT signing secret (crashes if missing) |
| `JWT_REFRESH_SECRET` | ✅ | Refresh token secret |
| `SINGULARITY_API_KEY` | ✅ | Singularity HTTP API key |
| `SINGULARITY_API_URL` | ❌ | Singularity URL (default: http://localhost:8450) |
| `SEED_ADMIN_PASSWORD` | ❌ | Admin user password for seeding |

## Modules

### Singularity AI Chat
Direct interface to Singularity's agent loop. Supports:
- Multi-session conversation management
- Real-time streaming responses
- Full access to Singularity's 28 tools through natural language
- Session history persistence (localStorage)

### CRM
- **Contacts:** Full CRUD with search, filter, status pipeline (Lead → Prospect → Customer → Churned)
- **Deals:** 5-stage Kanban (Qualified → Proposal → Negotiation → Closed Won/Lost) with probability tracking
- **Campaigns:** Email, social, ads, event campaign management with ROI tracking
- **Support:** Ticket management with priority and status tracking

### HRM
- Employee directory with department assignment
- Leave management and approval workflows
- Performance tracking
- Organizational structure visualization

### Finance
- Invoice generation and management
- Revenue tracking and forecasting
- Expense categorization
- Financial dashboard with KPIs

### Development
- Project management with sprint boards
- Repository integration
- Issue tracking
- Deployment pipeline monitoring

### Analytics
- Cross-module reporting
- Revenue trends
- Employee metrics
- Deal pipeline analytics

### Security
- Audit log viewer
- Role-based access control management
- Session monitoring
- Security event timeline

### Infrastructure
- Service health monitoring
- System resource tracking
- Deployment status
- Network topology

### Integrations
- Third-party service connections
- API key management
- Webhook configuration

### Workflows
- Automation pipeline builder
- Trigger-based actions
- Approval flows

### Stakeholders
- Investor relations management
- Board reporting
- Equity tracking
- Communication logs

### Admin
- User management (CRUD)
- Role and permission configuration
- System settings
- Feature flags

## Database Schema

8 models managed by Prisma ORM:

- **User** — Authentication, profile, role assignment
- **Role** — Permission groups (admin, user, custom)
- **Contact** — CRM contacts with company, status, notes
- **Deal** — Sales pipeline with stage, value, probability
- **Employee** — HR records with department, position, salary
- **Project** — Project management with status, dates, budget
- **Invoice** — Financial documents with line items, status
- **Activity** — Cross-module activity feed

## Security

- JWT authentication with separate access/refresh secrets
- bcrypt password hashing (10 salt rounds)
- Rate limiting (500 req/min, localhost exempt)
- CORS configuration
- Role-based route protection
- Input validation on all endpoints
- No default secret fallbacks (crashes on missing)

## Deployment

### systemd Service
```ini
[Service]
WorkingDirectory=/home/adam/workspace/singularity/erp/backend
ExecStart=/usr/bin/npx tsx src/index.ts
EnvironmentFile=/home/adam/workspace/singularity/erp/backend/.env
```

### nginx Reverse Proxy
Cloudflare Tunnel → nginx → localhost:3100

### Public URL
https://erp.artifactvirtual.com

## API Documentation

Swagger UI available at `/api/docs` when the backend is running.

---

*Part of the Singularity Autonomous Enterprise Runtime. Built by Artifact Virtual.*
