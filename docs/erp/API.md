# ERP API Reference

## Authentication

### POST /api/auth/register
Create a new user account.

**Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword",
  "firstName": "John",
  "lastName": "Doe"
}
```

**Response:** `201 Created`
```json
{
  "token": "eyJ...",
  "user": { "id": "uuid", "email": "user@example.com", "firstName": "John", "lastName": "Doe" }
}
```

### POST /api/auth/login
Authenticate and receive JWT.

**Body:**
```json
{
  "email": "admin@artifact.virtual",
  "password": "password"
}
```

**Response:** `200 OK`
```json
{
  "token": "eyJ...",
  "user": { "id": "uuid", "email": "admin@artifact.virtual", "role": "admin" }
}
```

### POST /api/auth/refresh
Refresh an expired access token.

**Headers:** `Authorization: Bearer <refresh_token>`

### POST /api/auth/forgot-password
Request password reset.

**Body:** `{ "email": "user@example.com" }`

### POST /api/auth/reset-password
Reset password with token.

**Body:** `{ "token": "reset_token", "password": "newpassword" }`

---

## Singularity AI

### POST /api/ai/chat
Send a message to Singularity and get a response.

**Headers:** `Authorization: Bearer <jwt_token>`

**Body:**
```json
{
  "message": "What systems do you manage?",
  "sessionId": "optional-session-id"
}
```

**Response:** `200 OK`
```json
{
  "response": "I manage 13 subsystems across the Artifact Virtual enterprise...",
  "sessionId": "http-erp-user@example.com",
  "durationMs": 7200
}
```

### GET /api/ai/health
Check Singularity connection status.

**Response:** `200 OK`
```json
{
  "status": "connected",
  "singularity": { "status": "ok", "uptime": 86400 }
}
```

---

## Contacts (CRM)

All endpoints require `Authorization: Bearer <jwt_token>`.

### GET /api/contacts
List all contacts. Supports query params: `?search=`, `?status=`, `?company=`

### POST /api/contacts
Create a contact.

### GET /api/contacts/:id
Get a single contact.

### PUT /api/contacts/:id
Update a contact.

### DELETE /api/contacts/:id
Delete a contact.

---

## Deals (CRM)

### GET /api/deals
List all deals. Supports `?stage=`, `?minValue=`, `?maxValue=`

### POST /api/deals
Create a deal.

### GET /api/deals/:id
Get a single deal.

### PUT /api/deals/:id
Update a deal (including stage transitions).

### DELETE /api/deals/:id
Delete a deal.

---

## Employees (HRM)

### GET /api/employees
### POST /api/employees
### GET /api/employees/:id
### PUT /api/employees/:id
### DELETE /api/employees/:id

---

## Projects

### GET /api/projects
### POST /api/projects
### GET /api/projects/:id
### PUT /api/projects/:id
### DELETE /api/projects/:id

---

## Invoices (Finance)

### GET /api/invoices
### POST /api/invoices
### GET /api/invoices/:id
### PUT /api/invoices/:id
### DELETE /api/invoices/:id

---

## Activities

### GET /api/activities
Get the activity feed. Supports `?type=`, `?limit=`

### POST /api/activities
Log an activity.

---

## Health

### GET /api/health
Backend health check.

**Response:** `200 OK`
```json
{
  "status": "ok",
  "timestamp": "2026-03-15T07:22:16.323Z"
}
```
