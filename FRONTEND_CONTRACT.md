# CodeBridge Frontend Contract & Integration Specification

> **Auditor Role:** Senior Backend/API Analyst  
> **Target Audience:** Frontend Engineering Team (React / Next.js)  
> **Workspace Scope:** `codebridge-backend` (FastAPI Microservices behind API Gateway)  
> **Specification Version:** 1.0.0 (Production Analysis)  
> **Methodology:** 100% Read-Only Static Codebase Extraction. No assertions are guessed; every claim is backed by exact repository files and line numbers.

---

## 1. Run Info

### 1.1 Gateway Exposure & Ports
* **Gateway Public Host & Port:** Exposed on `0.0.0.0:8000` (primary) and `0.0.0.0:8080` (secondary alias) mapped to internal container port `8000`.
  * *Source:* [`docker-compose.yml:88-90`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/docker-compose.yml#L88-L90), [`api-gateway/app/config.py:44-45`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/config.py#L44-L45)
* **Path Prefix Architecture:** 
  * The gateway mounts proxy routing **both** at the root `/` and under the versioned prefix `/api/v1`.
  * *Source:* [`api-gateway/app/main.py:86-90`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/main.py#L86-L90), [`api-gateway/app/config.py:46`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/config.py#L46)
  * Public frontend requests should target `http://localhost:8000/api/v1/...` (or direct path `http://localhost:8000/...`).
* **Health & Operational Check URLs:**
  * Gateway Liveness: `GET http://localhost:8000/health` (Returns `{"status": "healthy", "service": "api-gateway", "version": "1.0.0", "redis": "connected"|"disabled"}`)
    * *Source:* [`api-gateway/app/routes/health.py:11-25`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/routes/health.py#L11-L25)
  * Gateway Readiness: `GET http://localhost:8000/ready` (Returns HTTP 200 `ready` or HTTP 503 `not_ready`)
    * *Source:* [`api-gateway/app/routes/health.py:28-40`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/routes/health.py#L28-L40)
  * Downstream Service Health via Gateway: Each downstream service's `/health` endpoint is reachable at `http://localhost:8000/<service_prefix>/health` or directly on internal ports.
* **Interactive API Documentation (Swagger / OpenAPI):**
  * Gateway Swagger UI: `http://localhost:8000/docs`
  * Gateway OpenAPI JSON: `http://localhost:8000/openapi.json`
  * Gateway ReDoc: `http://localhost:8000/redoc`
  * Downstream Services: Available in development environments when directly accessing service internal ports (e.g. `http://localhost:8001/docs` for Identity Service). In production, documentation routes are restricted.
    * *Source:* [`services/code-context-service/app/main.py:115-117`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/code-context-service/app/main.py#L115-L117)

### 1.2 Routing Table (Gateway Prefix -> Downstream Service -> Internal Port)
The API Gateway uses deterministic prefix matching with priority ordering to proxy requests down to microservices over HTTPX persistent connection pools.

*Source:* [`api-gateway/app/clients/service_registry.py:123-190`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/clients/service_registry.py#L123-L190), [`docker-compose.yml:54-513`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/docker-compose.yml#L54-L513)

| Gateway Public Prefix | Downstream Service Name | Downstream Internal URL | Container Port | Downstream Internal Target Path | Match Priority |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/auth` | `identity-service` | `http://identity-service:8001` | 8001 | `/api/v1/auth` | 100 |
| `/freelancers` | `identity-service` | `http://identity-service:8001` | 8001 | `/api/v1/freelancers` | 100 |
| `/profile` | `identity-service` | `http://identity-service:8001` | 8001 | `/api/v1/profile` | 100 |
| `/users` | `identity-service` | `http://identity-service:8001` | 8001 | `/api/v1/users` | 100 |
| `/talent` | `identity-service` | `http://identity-service:8001` | 8001 | `/api/v1/talent` | 100 |
| `/projects` | `project-service` | `http://project-service:8002` | 8002 | `/api/v1/projects` | 100 |
| `/tasks` | `project-service` | `http://project-service:8002` | 8002 | `/api/v1/tasks` | 100 |
| `/projects/{project_id}/github` | `github-service` | `http://github-service:8003` | 8003 | `/api/v1/projects/{project_id}/github` | 10 |
| `/github` | `github-service` | `http://github-service:8003` | 8003 | `/api/v1/github` | 100 |
| `/code-context` | `code-context-service` | `http://code-context-service:8004` | 8004 | `/api/v1/code-context` | 100 |
| `/ai` | `code-context-service` | `http://code-context-service:8004` | 8004 | `/api/v1/ai` | 100 |
| `/workspace` | `workspace-service` | `http://workspace-service:8005` | 8005 | `/api/v1/workspace` | 100 |
| `/workspaces` | `workspace-service` | `http://workspace-service:8005` | 8005 | `/api/v1/workspaces` | 100 |
| `/submissions` | `review-service` | `http://review-service:8006` | 8006 | `/api/v1/submissions` | 100 |
| `/review` | `review-service` | `http://review-service:8006` | 8006 | `/api/v1/review` | 100 |
| `/profile/verified-work` | `verification-service`| `http://verification-service:8007`| 8007 | `/api/v1/verification/me` | 10 |
| `/verification` | `verification-service`| `http://verification-service:8007`| 8007 | `/api/v1/verification` | 100 |
| `/payments/summary` | `payment-service` | `http://payment-service:8008` | 8008 | `/api/v1/payment/summary` | 10 |
| `/payment/summary` | `payment-service` | `http://payment-service:8008` | 8008 | `/api/v1/payment/summary` | 10 |
| `/payments` | `payment-service` | `http://payment-service:8008` | 8008 | `/api/v1/payment` | 100 |
| `/payment` | `payment-service` | `http://payment-service:8008` | 8008 | `/api/v1/payment` | 100 |
| `/notifications` | `notification-service` | `http://notification-service:8009`| 8009 | `/api/v1/notifications` | 100 |
| `/admin` | `admin-service` | `http://admin-service:8010` | 8010 | `/api/v1/admin` | 100 |
| `/audit` | `audit-service` | `http://audit-service:8011` | 8011 | `/api/v1/audit` | 100 |
| `/observability` | `observability-service` | `http://observability-service:8012`| 8012 | `/api/v1/observability` | 100 |

### 1.3 Minimum Environment Variables Required for Auth & Basic Run
To run the authentication loop (`register`, `login`, `refresh`, `logout`, `me`) across the gateway and `identity-service`, the following environment variables are strictly required:

*Source:* [`docker-compose.yml:38-42, 60-87, 110-120`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/docker-compose.yml#L38-L42), [`api-gateway/app/config.py:29-88`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/config.py#L29-L88), [`services/identity-service/app/core/config.py:17-56`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/core/config.py#L17-L56)

1. **`JWT_SECRET_KEY`**: Symmetric secret key (minimum 32 bytes) used to sign and verify HMAC-SHA256 access and refresh tokens. Must match across `api-gateway` and `identity-service`.
2. **`POSTGRES_USER`**, **`POSTGRES_PASSWORD`**, **`POSTGRES_HOST`**, **`POSTGRES_PORT`**: Credentials for PostgreSQL connection pool.
3. **`DATABASE_URL`** (in `identity-service`): Async PostgreSQL DSN: `postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/codebridge_identity`.
4. **`IDENTITY_SERVICE_URL`** (in `api-gateway`): Base URL pointing to Identity microservice (`http://identity-service:8001` or `http://localhost:8001`).
5. **`CORS_ORIGINS`**: Frontend URL (e.g. `http://localhost:3000` or `*` for open development).
6. **`REDIS_URL`** (optional, recommended): Enables distributed rate limiting and token revocation blacklisting. Defaults to disabled in-memory fallback if absent.

---

## 2. CORS and Cookies

### 2.1 CORS Configuration
*Source:* [`api-gateway/app/main.py:64-79`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/main.py#L64-L79), [`api-gateway/app/config.py:50-60, 153-170`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/config.py#L50-L60)

* **Allowed Origins (`allow_origins`):** Controlled by `CORS_ORIGINS`. In development defaults to `["*"]`.
* **Allowed Origin Regex (`allow_origin_regex`):** `r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://.*\.loca\.lt"`
  * This explicitly permits any port on `localhost` or `127.0.0.1` (e.g. Next.js on `3000`, Vite on `5173`) and any `localtunnel` tunnel (`*.loca.lt`).
* **Allow Credentials (`allow_credentials`):** `True` (hardcoded in `api-gateway/app/main.py:68` for cookie & authorization forwarding).
  * *Note:* When `APP_ENV=production`, `*` wildcard origin combined with credentials is fundamentally rejected by Pydantic validation rule [`api-gateway/app/config.py:155-158`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/config.py#L155-L158).
* **Allowed Methods (`allow_methods`):** `["*"]` (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, `HEAD`).
* **Allowed Headers (`allow_headers`):** `["*"]` (including `Authorization`, `Content-Type`, `Idempotency-Key`, `X-Request-ID`, `X-Correlation-Id`).
* **Exposed Response Headers (`expose_headers`):**
  * `X-Request-ID`
  * `X-Correlation-Id`
  * `X-RateLimit-Limit`
  * `X-RateLimit-Remaining`
  * `X-RateLimit-Reset`
  * `Retry-After`

### 2.2 Cookies Set by Backend
The backend sets exactly **one** authentication session cookie:

*Source:* [`services/identity-service/app/api/routes/auth.py:104-111, 163-170, 212`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L104-L111)

| Cookie Name | Purpose | HttpOnly | Secure | SameSite | Path | Domain | Max-Age | Set On Endpoints |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `refresh_token` | Rotating refresh token session | `True` | `False` (in dev) / env | `lax` | `/` | Host-only (omitted) | `604800` (7 days = `REFRESH_TOKEN_EXPIRE_DAYS * 86400`) | `POST /auth/login`, `POST /auth/refresh` |
| `refresh_token` (deletion) | Session revocation on logout | `True` | `False` / env | `lax` | `/` | Host-only | `0` (expires immediately) | `POST /auth/logout` |

*Gateway Cookie Propagation:* The API Gateway proxy explicitly preserves downstream `Set-Cookie` and client `Cookie` headers without stripping them ([`api-gateway/app/routes/proxy.py:213-221`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/routes/proxy.py#L213-L221)).

---

## 3. Authentication & User Management

### 3.1 Auth Architecture Overview
* **Token Type:** Signed JSON Web Tokens (JWT) using algorithm **`HS256`** ([`services/identity-service/app/core/config.py:44`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/core/config.py#L44)).
* **Access Token Lifetime:** **15 minutes** (900 seconds) ([`services/identity-service/app/core/config.py:45`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/core/config.py#L45)).
* **Refresh Token Lifetime:** **7 days** (604,800 seconds) ([`services/identity-service/app/core/config.py:46`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/core/config.py#L46)).
* **Refresh Token Transport:** Travels in **both** the `refresh_token` HTTP cookie **and** the JSON response body ([`services/identity-service/app/api/routes/auth.py:104-111, 121`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L104-L111)).
* **Password Hashing Scheme:** **Argon2id** (`argon2-cffi`) ([`services/identity-service/app/core/config.py:47`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/core/config.py#L47), [`services/identity-service/app/core/security.py:30-45`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/core/security.py#L30-L45)).
* **Password Rules:**
  * Public Registration: Minimum 6 characters, maximum 128 characters ([`services/identity-service/app/schemas/auth.py:27`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/auth.py#L27)).
  * Admin Account Provisioning: Minimum 8 characters, maximum 128 characters; must contain uppercase, lowercase, digit, and special symbol ([`services/identity-service/app/schemas/user.py:66-77`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/user.py#L66-L77)).
* **User ID Type:** Canonical **UUIDv4** string (e.g. `3fa85f64-5717-4562-b3fc-2c963f66afa6`) ([`services/identity-service/app/models/user.py:33-37`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/models/user.py#L33-L37)).
* **Platform User Roles:** Canonical uppercase enum in database:
  * `"OWNER"`
  * `"FREELANCER"`
  * `"ADMIN"`
  * *Source:* [`services/identity-service/app/models/user.py:20-26`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/models/user.py#L20-L26)

---

### 3.2 Endpoint: Register
* **Path:** `POST /api/v1/auth/register` (also `/auth/register`)
* **Auth Needed:** None (Public)
* **Status Code:** `201 Created` (409 Conflict if email exists, 403 Forbidden if ADMIN requested, 422 Unprocessable Entity)
* **Source:** [`services/identity-service/app/api/routes/auth.py:36-74`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L36-L74), [`services/identity-service/app/schemas/auth.py:20-65`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/auth.py#L20-L65)

#### Request JSON:
```json
{
  "email": "developer@example.com",
  "password": "StrongPassword123!",
  "full_name": "Alex Mercer",
  "role": "FREELANCER"
}
```
*Frontend Compatibility Notes:*
* `displayName`, `name`, or `username` are automatically mapped to `full_name` by backend preprocessor ([`services/identity-service/app/schemas/auth.py:34-43`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/auth.py#L34-L43)).
* Lowercase roles `"owner"` and `"freelancer"` are automatically converted to uppercase `"OWNER"` and `"FREELANCER"` ([`services/identity-service/app/schemas/auth.py:45-52`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/auth.py#L45-L52)).
* Public registration of `"ADMIN"` is rejected with HTTP 403.

#### Success Response JSON (HTTP 201):
```json
{
  "id": "c1f7b8c2-2849-4177-bb89-7cf1f7823f66",
  "full_name": "Alex Mercer",
  "displayName": "Alex Mercer",
  "email": "developer@example.com",
  "role": "FREELANCER",
  "is_active": true,
  "is_verified": false,
  "status": "active",
  "onboardingCompleted": true,
  "onboarding_completed": true,
  "created_at": "2026-11-17T12:00:00Z",
  "updated_at": "2026-11-17T12:00:00Z"
}
```

---

### 3.3 Endpoint: Login
* **Path:** `POST /api/v1/auth/login` (also `/auth/login`)
* **Auth Needed:** None (Public)
* **Status Code:** `200 OK` (401 Unauthorized for invalid credentials, 403 Forbidden for inactive account, 429 for rate limit)
* **Source:** [`services/identity-service/app/api/routes/auth.py:77-122`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L77-L122), [`services/identity-service/app/schemas/auth.py:67-79, 113-134`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/auth.py#L67-L79)

#### Request JSON:
```json
{
  "email": "developer@example.com",
  "password": "StrongPassword123!"
}
```

#### Success Response JSON (HTTP 200):
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "expiresIn": 900,
  "refresh_expires_in": 604800,
  "user": {
    "id": "c1f7b8c2-2849-4177-bb89-7cf1f7823f66",
    "full_name": "Alex Mercer",
    "displayName": "Alex Mercer",
    "email": "developer@example.com",
    "role": "FREELANCER",
    "is_active": true,
    "is_verified": false,
    "status": "active",
    "onboardingCompleted": true,
    "created_at": "2026-11-17T12:00:00Z",
    "updated_at": "2026-11-17T12:00:00Z"
  }
}
```

---

### 3.4 Endpoint: Refresh Token Rotation
* **Path:** `POST /api/v1/auth/refresh` (also `/auth/refresh`)
* **Auth Needed:** Valid `refresh_token` in cookie OR JSON body
* **Status Code:** `200 OK` (401 Unauthorized for invalid/expired/revoked token, 403 Forbidden for inactive account)
* **Source:** [`services/identity-service/app/api/routes/auth.py:124-172`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L124-L172), [`services/identity-service/app/schemas/auth.py:81-95`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/auth.py#L81-L95)

#### Request JSON (Optional if cookie is supplied):
```json
{
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```
*Note:* The schema accepts both `"refreshToken"` and `"refresh_token"`. If body is omitted or `{}` is sent, the server extracts `refresh_token` directly from request cookies ([`services/identity-service/app/api/routes/auth.py:154`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L154)).

#### Success Response JSON:
Identical to the login `TokenPairResponse` (returns new rotated access token and refresh token).

---

### 3.5 Endpoint: Logout
* **Path:** `POST /api/v1/auth/logout` (also `/auth/logout`)
* **Auth Needed:** `Authorization: Bearer <access_token>`
* **Status Code:** `200 OK`
* **Source:** [`services/identity-service/app/api/routes/auth.py:174-226`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L174-L226)

#### Request Body (Optional):
```json
{
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```
*Action:* Revokes the refresh token family in PostgreSQL, blacklists the active access token `jti` in Redis, and instructs browser to delete cookie `Set-Cookie: refresh_token=; Max-Age=0; Path=/`.

#### Success Response JSON:
```json
{
  "message": "Logged out successfully."
}
```

---

### 3.6 Endpoint: Current User Identity ("Me")
* **Path:** `GET /api/v1/auth/me` OR `GET /api/v1/users/me` OR `GET /api/v1/auth/users/me`
* **Auth Needed:** `Authorization: Bearer <access_token>`
* **Status Code:** `200 OK` (401 Unauthorized)
* **Source:** [`services/identity-service/app/api/routes/auth.py:228-252`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L228-L252), [`services/identity-service/app/api/routes/users.py:16-25`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/users.py#L16-L25)

#### Success Response JSON:
```json
{
  "id": "c1f7b8c2-2849-4177-bb89-7cf1f7823f66",
  "full_name": "Alex Mercer",
  "displayName": "Alex Mercer",
  "email": "developer@example.com",
  "role": "FREELANCER",
  "is_active": true,
  "is_verified": false,
  "status": "active",
  "onboardingCompleted": true,
  "created_at": "2026-11-17T12:00:00Z",
  "updated_at": "2026-11-17T12:00:00Z"
}
```

---

## 4. Error Format & Response Envelope

### 4.1 Standard JSON Error Shape
All client errors (4xx) and internal errors (5xx) routed through the API Gateway are intercepted, sanitized, and normalized into a single canonical error envelope.

*Source:* [`api-gateway/app/core/exceptions.py:154-174, 176-254`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/core/exceptions.py#L154-L174)

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed."
  },
  "request_id": "8c6b7588-4ff5-4ca3-b89e-ec86b51cfa44"
}
```

### 4.2 Canonical Error Codes & HTTP Status Mapping
*Source:* [`api-gateway/app/core/exceptions.py:131-152`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/core/exceptions.py#L131-L152)

| HTTP Status | Error Code (`error.code`) | Default Message (`error.message`) | Typical Cause |
| :--- | :--- | :--- | :--- |
| **400** | `VALIDATION_ERROR` | `"The request could not be validated."` | Malformed parameters, illegal path traversal |
| **401** | `UNAUTHORIZED` | `"Authentication is required."` | Missing, invalid, expired, or blacklisted JWT |
| **403** | `FORBIDDEN` | `"You do not have permission to perform this action."` | Role mismatch (e.g. non-OWNER accessing owner routes) |
| **404** | `NOT_FOUND` | `"The requested endpoint was not found."` | Unmatched path or non-existent database ID |
| **405** | `VALIDATION_ERROR` | `"HTTP method is not allowed for this endpoint."` | Method not allowed |
| **409** | `CONFLICT` | `"The request conflicts with the current resource state."` | Duplicate email, duplicate project publishing, state conflict |
| **422** | `VALIDATION_ERROR` | `"Request validation failed."` | Pydantic payload schema violation |
| **429** | `RATE_LIMIT_EXCEEDED` / `RATE_LIMITED` | `"Too many requests. Please wait before retrying."` | Exceeded 120 req/min (general) or 20 req/min (auth) |
| **500** | `INTERNAL_SERVER_ERROR`| `"An unexpected internal server error occurred."` | Unhandled runtime exception (stack traces redacted) |
| **502** | `SERVICE_UNAVAILABLE` | `"An upstream service error occurred."` | Downstream service crash or connection failure |
| **503** | `SERVICE_UNAVAILABLE` | `"The requested service is currently unavailable."` | Downstream service not booted or database connection down |
| **504** | `SERVICE_TIMEOUT` | `"The upstream service timed out while processing the request."` | Synchronous downstream call exceeded 10.0s |

### 4.3 Correlation & Tracing Headers
* **Header Name:** `X-Request-ID` (and echoed as `X-Correlation-Id`).
* **Generation & Propagation:** If incoming request omits `X-Request-ID`, the gateway generates a fresh UUIDv4. If the client sends `X-Request-ID`, it is validated as a canonical UUID and forwarded downstream to all microservices and database queries.
* **Response Header:** The gateway always attaches `X-Request-ID: <uuid>` to **every** HTTP response.
* *Source:* [`api-gateway/app/middleware/correlation.py:16-36, 42-65`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/middleware/correlation.py#L16-L36)

---

## 5. Microservices Route Catalog (Every Service & Route)

Below is the verified inventory of all **74 endpoints** mapped through the API Gateway into the 12 downstream services.

### 5.1 Identity Service (Port 8001)
*Source:* [`services/identity-service/app/api/routes/auth.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py), [`profile.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/profile.py), [`freelancers.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/freelancers.py), [`users.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/users.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | Public | `email`, `password`, `full_name` (or `displayName`), `role` (`OWNER`\|`FREELANCER`) | `id`, `email`, `full_name`, `displayName`, `role`, `is_active`, `status` |
| `POST` | `/api/v1/auth/login` | Public | `email`, `password` | `accessToken`, `refreshToken`, `expiresIn`, `user` object |
| `POST` | `/api/v1/auth/refresh` | Valid Refresh Token | `refreshToken` (optional if cookie sent) | `accessToken`, `refreshToken`, `expiresIn`, `user` object |
| `POST` | `/api/v1/auth/logout` | Bearer Token | `refreshToken` (optional if cookie sent) | `message: "Logged out successfully."` |
| `GET` | `/api/v1/auth/me` | Bearer (Any) | None | `id`, `email`, `displayName`, `role`, `status`, `onboardingCompleted` |
| `GET` | `/api/v1/users/me` | Bearer (Any) | None | `id`, `email`, `displayName`, `role`, `status`, `onboardingCompleted` |
| `PUT` | `/api/v1/users/me/owner-profile`| Bearer (Any) | Free-form JSON (`organizationName`, `ownerType`, etc.) | `{"profile": {...}, "onboardingCompleted": true}` |
| `PATCH`| `/api/v1/users/me/owner-profile`| Bearer (Any) | Free-form JSON (`organizationName`, etc.) | `{"profile": {...}, "onboardingCompleted": true}` |
| `PUT` | `/api/v1/talent/profiles/me` | Bearer (Any) | Free-form JSON (`headline`, `skills`, `githubUsername`, etc.) | `{"profile": {...}, "onboardingCompleted": true}` |
| `PATCH`| `/api/v1/talent/profiles/me` | Bearer (Any) | Free-form JSON | `{"profile": {...}, "onboardingCompleted": true}` |
| `GET` | `/api/v1/profile` | Bearer (Any) | None | `id`, `full_name`, `email`, `role`, `freelancer_profile` |
| `PATCH`| `/api/v1/profile` | Bearer (Any) | `full_name` | `id`, `full_name`, `email`, `role`, `freelancer_profile` |
| `GET` | `/api/v1/freelancers` | Public | Query: `page`, `page_size`, `search`, `skill`, `availability` | `items` (list of public profiles), `total`, `page`, `page_size` |
| `PATCH`| `/api/v1/freelancers/me` | Bearer (`FREELANCER`)| `bio`, `skills` (list), `experience_years`, `availability` | Updated `FreelancerProfileDetail` object |
| `GET` | `/api/v1/freelancers/{id}`| Public | Path: `id` (UUID) | Public profile details, `skills`, `experience_years`, `availability` |
| `POST` | `/api/v1/auth/admin/users` | Bearer (`ADMIN`)| `full_name`, `email`, `password`, `role`, `is_verified` | Created `UserPublicResponse` |
| `GET` | `/api/v1/auth/admin/users` | Bearer (`ADMIN`)| Query: `page`, `page_size`, `role` | Paginated `AdminUserListResponse` |
| `PATCH`| `/api/v1/auth/admin/users/{id}/status`| Bearer (`ADMIN`)| `is_active` (bool), `is_verified` (bool) | Updated `UserPublicResponse` |

---

### 5.2 Project Service (Port 8002)
*Source:* [`services/project-service/app/api/routes/projects.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/projects.py), [`assignments.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/assignments.py), [`tasks.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/tasks.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/projects` | Bearer (`OWNER`) | `title`, `description`, `budget`, `currency`, `deadline`, `required_skills` (or `tags`), `expected_result` | `id`, `owner_id`, `title`, `status` (`OPEN`), `budget`, `requirements` |
| `GET` | `/api/v1/projects` | Bearer (Any) | Query: `page`, `page_size`, `status`, `search`, `skill`, `deadline_before` | `items` (list of projects scoped to role), `total`, `page` |
| `GET` | `/api/v1/projects/{id}` | Bearer (Any) | Path: `id` (UUID) | Project details, requirement details, active assignments |
| `PATCH`| `/api/v1/projects/{id}` | Bearer (`OWNER`) | `title`, `description`, `budget`, `deadline`, `required_skills` | Updated `ProjectResponse` |
| `POST` | `/api/v1/projects/{id}/publish` | Bearer (`OWNER`) | None | `ProjectResponse` with `status: "OPEN"` |
| `POST` | `/api/v1/projects/{id}/cancel` | Bearer (`OWNER`) | None | `ProjectResponse` with `status: "CANCELLED"` |
| `POST` | `/api/v1/projects/{id}/select-freelancer` | Bearer (`OWNER`) | `freelancer_id` (UUID) | `AssignmentResponse`, `status: "ASSIGNED"` |
| `POST` | `/api/v1/projects/{id}/workflow/transition` | Bearer (`OWNER`\|`FREELANCER`) | `target_status`, `approval_verified` | Project transition result |
| `GET` | `/api/v1/tasks/mine` | Bearer (Any) | None | `{"items": [{"id", "title", "projectTitle", "status", "reward", "dueAt"}]}` |
| `GET` | `/api/v1/tasks/{task_id}` | Bearer (Any) | Path: `task_id` | `id`, `title`, `repo` (`name`, `branch`), `brief`, `criteria`, `history` |

---

### 5.3 GitHub Service (Port 8003)
*Source:* [`services/github-service/app/api/routes/oauth.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/github-service/app/api/routes/oauth.py), [`repositories.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/github-service/app/api/routes/repositories.py), [`project_github.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/github-service/app/api/routes/project_github.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/github/oauth/authorize` | Bearer (`OWNER`) | Query: `project_id` (UUID) | HTTP 302 Redirect to GitHub OAuth App login |
| `GET` | `/api/v1/github/oauth/callback` | Public / Query | Query: `code`, `state`, `error` | Connection metadata or HTTP 302 frontend redirect |
| `DELETE`| `/api/v1/github/connection` | Bearer (`OWNER`) | None | `disconnected: true`, `owner_id` |
| `GET` | `/api/v1/github/link/me` | Bearer / Optional | None | `{"connected": bool, "githubUsername": str}` |
| `POST` | `/api/v1/github/link/mock` | Bearer / Optional | `githubUsername` | `{"connected": true, "githubUsername": str}` |
| `GET` | `/api/v1/github/repositories` | Bearer (`OWNER`) | Query: `page`, `per_page`, `visibility` | List of accessible repositories with safe metadata |
| `POST` | `/api/v1/projects/{id}/github/connect` | Bearer (`OWNER`) | `github_repo_id`, `repo_name`, `default_branch` | `ProjectRepositoryMetadata` (`connected_at`, `repo_name`) |
| `GET` | `/api/v1/projects/{id}/github/status` | Bearer (Any) | Path: `id` (UUID) | `ProjectGitHubStatusResponse` (`connected`, `repo_name`) |
| `DELETE`| `/api/v1/projects/{id}/github/disconnect` | Bearer (`OWNER`) | Path: `id` (UUID) | Disconnect status |
| `GET` | `/api/v1/projects/{id}/github/branches` | Bearer (`OWNER`) | Query: `page`, `per_page` | `BranchListResponse` (branch names, commit shas) |
| `GET` | `/api/v1/projects/{id}/github/contents` | Bearer (`OWNER`) | Query: `path`, `ref` | File content or directory listing |
| `GET` | `/api/v1/projects/{id}/github/commits` | Bearer (`OWNER`) | Query: `sha`, `path`, `page`, `per_page` | Commit history (messages, author, timestamp) |
| `GET` | `/api/v1/projects/{id}/github/snapshot` | Bearer (`OWNER`\|`FREELANCER`) | Query: `ref` | Bounded zip archive stream (`application/zip`) |

---

### 5.4 Code Context & AI Service (Port 8004)
*Source:* [`services/code-context-service/app/api/routes/indexing.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/code-context-service/app/api/routes/indexing.py), [`query.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/code-context-service/app/api/routes/query.py), [`insights.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/code-context-service/app/api/routes/insights.py), [`ai_context.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/code-context-service/app/api/routes/ai_context.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/code-context/projects/{id}/index` | Bearer (`OWNER`) | `branch` (optional) | `status: "INDEXING"`, `version`, `task_id` |
| `POST` | `/api/v1/code-context/projects/{id}/reindex` | Bearer (`OWNER`) | `branch` (optional) | `status: "INDEXING"`, `version` |
| `GET` | `/api/v1/code-context/projects/{id}/index/status` | Bearer (Any) | None | `status`, `files_indexed`, `chunks_count`, `languages` |
| `POST` | `/api/v1/code-context/projects/{id}/query` | Bearer (`OWNER`\|`FREELANCER`) | `query`, `top_k`, `file_filter` | `answer`, `citations` (`file_path`, `snippet`, `score`) |
| `POST` | `/api/v1/code-context/projects/{id}/insights/generate` | Bearer (`OWNER`) | `include_ai_summary` (bool) | Generated architecture insights report |
| `GET` | `/api/v1/code-context/projects/{id}/insights` | Bearer (Any) | None | Latest architecture insights report |
| `GET` | `/api/v1/ai/context/{task_id}` | Bearer (Any) | Path: `task_id` | `summary`, `findings` (list), `relevantFiles` (list), `approach` (list) |

---

### 5.5 Workspace Service (Port 8005)
*Source:* [`services/workspace-service/app/api/routes/workspaces.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/workspace-service/app/api/routes/workspaces.py), [`task_workspaces.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/workspace-service/app/api/routes/task_workspaces.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/workspace/projects/{id}` | Bearer (`OWNER`\|`FREELANCER`) | `ttl_minutes`, `image_tag` | `workspace_id`, `status: "READY"`, `container_id` |
| `GET` | `/api/v1/workspace/projects/{id}` | Bearer (Any) | None | List of workspaces for project |
| `GET` | `/api/v1/workspace/{workspace_id}` | Bearer (Any) | Path: `workspace_id` | Workspace detail, runtime specs, timestamps |
| `POST` | `/api/v1/workspace/{workspace_id}/start` | Bearer (`OWNER`\|`FREELANCER`) | None | `status: "RUNNING"` |
| `POST` | `/api/v1/workspace/{workspace_id}/stop` | Bearer (`OWNER`\|`FREELANCER`) | None | `status: "STOPPED"` |
| `POST` | `/api/v1/workspace/{workspace_id}/refresh`| Bearer (`OWNER`\|`FREELANCER`) | None | `status: "READY"` with fresh snapshot |
| `GET` | `/api/v1/workspace/{workspace_id}/logs` | Bearer (Any) | Query: `tail` (1..500) | Sanitized stdout/stderr log lines |
| `POST` | `/api/v1/workspace/{workspace_id}/run-tests`| Bearer (`OWNER`\|`FREELANCER`) | `test_command` (optional) | `exit_code`, `passed: bool`, `output` |
| `DELETE`| `/api/v1/workspace/{workspace_id}` | Bearer (`OWNER`\|`FREELANCER`) | None | `status: "DESTROYED"` |
| `POST` | `/api/v1/workspace/cleanup-expired` | Bearer (`OWNER`\|`ADMIN`) | None | Count of cleaned containers |
| `GET` | `/api/v1/workspaces/{task_id}` | Bearer (Any) | Path: `task_id` | `status`, `image`, `cpu`, `memory`, `repoAccess` |
| `POST` | `/api/v1/workspaces/{task_id}/start` | Bearer (Any) | None | `{"status": "running"}` |
| `POST` | `/api/v1/workspaces/{task_id}/stop` | Bearer (Any) | None | `{"status": "stopped"}` |
| `POST` | `/api/v1/workspaces/{task_id}/reset` | Bearer (Any) | None | `{"status": "running"}` |
| `GET` | `/api/v1/workspaces/{task_id}/files` | Bearer (Any) | None | `commit`, `items: [{"path", "type", "size"}]` |
| `GET` | `/api/v1/workspaces/{task_id}/files/content` | Bearer (Any) | Query: `path` | `path`, `language`, `content` |
| `PUT` | `/api/v1/workspaces/{task_id}/files/content` | Bearer (Any) | `path`, `content` | `{"savedAt": "<timestamp>"}` |
| `POST` | `/api/v1/workspaces/{task_id}/files/content` | Bearer (Any) | `path`, `content` | `{"savedAt": "<timestamp>"}` |

---

### 5.6 Review Service (Port 8006)
*Source:* [`services/review-service/app/api/routes/submissions.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/review-service/app/api/routes/submissions.py), [`review.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/review-service/app/api/routes/review.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/submissions/projects/{id}` | Bearer (`FREELANCER`)| `summary`, `files` (list), `commit_sha` | Created `SubmissionResponse` (`status: "DRAFT"`) |
| `GET` | `/api/v1/submissions/projects/{id}` | Bearer (Any) | None | List of submissions for project |
| `POST` | `/api/v1/submissions/runs` | Bearer (Any) | `taskId` (string) | `{"runId": "run_..."}` |
| `GET` | `/api/v1/submissions/runs/{run_id}` | Bearer (Any) | Path: `run_id` | `runId`, `taskId`, `status`, `results: [{"testId", "status", "message"}]` |
| `POST` | `/api/v1/submissions` | Bearer (Any) | `taskId`, `notes` | `{"submissionId": "sub_...", "status": "in_review"}` |
| `GET` | `/api/v1/submissions/current` | Bearer (Any) | Query: `taskId` | `status: "in_review"|"none"`, `note`, `lastRun` |
| `GET` | `/api/v1/submissions/{id}` | Bearer (Any) | Path: `id` (UUID) | Submission record, files changed, review decision |
| `POST` | `/api/v1/submissions/{id}/submit` | Bearer (`FREELANCER`)| None | `status: "SUBMITTED"` |
| `POST` | `/api/v1/submissions/{id}/withdraw`| Bearer (`FREELANCER`)| None | `status: "WITHDRAWN"` |
| `POST` | `/api/v1/submissions/{id}/comments`| Bearer (Any) | `comment`, `file_path`, `line_number` | Created comment record |
| `POST` | `/api/v1/review/submissions/{id}/start` | Bearer (`OWNER`) | None | Review started, `status: "UNDER_REVIEW"` |
| `POST` | `/api/v1/review/submissions/{id}/decision` | Bearer (`OWNER`) | `decision` (`APPROVED`\|`CHANGES_REQUESTED`\|`REJECTED`), `feedback` | Decided `SubmissionResponse` |
| `GET` | `/api/v1/review/submissions/{id}` | Bearer (Any) | Path: `id` (UUID) | Submission review details |
| `GET` | `/api/v1/review/projects/{id}` | Bearer (Any) | Path: `id` (UUID) | Consolidated project review summary |

---

### 5.7 Verification Service (Port 8007)
*Source:* [`services/verification-service/app/api/routes/verification.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/verification-service/app/api/routes/verification.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/verification/records` | Bearer (`OWNER`\|`ADMIN`) | `project_id`, `freelancer_id`, `submission_id` | Cryptographically signed `VerifiedWorkRecordResponse` |
| `GET` | `/api/v1/verification/public/{id}`| Public | Path: `id` (public code) | Non-sensitive verified credentials, project badge |
| `GET` | `/api/v1/verification/me` | Bearer (Any) | None | Caller's list of verified work records |
| `GET` | `/api/v1/profile/verified-work` | Bearer (Any) | None | Gateway alias to `/verification/me` |
| `GET` | `/api/v1/verification/freelancers/{id}`| Public | Path: `id` (UUID) | Public freelancer verified credentials portfolio |
| `GET` | `/api/v1/verification/projects/{id}` | Bearer (Any) | Path: `id` (UUID) | Verified records attached to project |
| `GET` | `/api/v1/verification/records/{id}` | Bearer (Any) | Path: `id` (UUID) | Full verified record with cryptographic signature |
| `POST` | `/api/v1/verification/records/{id}/verify`| Public | Path: `id` (UUID) | `signature_valid: bool`, `tampered: false` |
| `POST` | `/api/v1/verification/records/{id}/revoke`| Bearer (`OWNER`\|`ADMIN`) | `reason` | Revocation status |

---

### 5.8 Payment & Escrow Service (Port 8008)
*Source:* [`services/payment-service/app/api/routes/payment.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/payment-service/app/api/routes/payment.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/payment/summary` | Bearer (Any) | None | `total_spent`, `total_escrow`, `held`, `pendingRelease`, `released`, `items` |
| `GET` | `/api/v1/payments/summary` | Bearer (Any) | None | Gateway alias to `/payment/summary` |
| `GET` | `/api/v1/payment/escrow/{task_id}` | Bearer (Any) | Path: `task_id` | `{"status": "funded", "reward": 4500.0, "currency": "USD", "fundedAt": ...}` |
| `POST` | `/api/v1/payment/projects/{id}/escrow` | Bearer (`OWNER`\|`ADMIN`) | `amount`, `currency` | Created `EscrowPaymentResponse` (`status: "CREATED"`) |
| `POST` | `/api/v1/payment/escrows/{id}/fund` | Bearer (`OWNER`\|`ADMIN`) | `amount` | `status: "FUNDED"` |
| `POST` | `/api/v1/payment/escrows/{id}/hold` | Bearer (`OWNER`\|`ADMIN`) | `reason` | `status: "HELD"` |
| `POST` | `/api/v1/payment/escrows/{id}/release`| Bearer (`OWNER`\|`ADMIN`) | None | `status: "RELEASED"` |
| `POST` | `/api/v1/payment/escrows/{id}/refund` | Bearer (`OWNER`\|`ADMIN`) | `amount`, `reason` | `status: "REFUNDED"` |
| `POST` | `/api/v1/payment/escrows/{id}/cancel` | Bearer (`OWNER`\|`ADMIN`) | `reason` | `status: "CANCELLED"` |
| `GET` | `/api/v1/payment/projects/{id}` | Bearer (Any) | Path: `id` (UUID) | List of escrows tied to project |
| `GET` | `/api/v1/payment/escrows/{id}` | Bearer (Any) | Path: `id` (UUID) | Detailed escrow status and ledger history |
| `GET` | `/api/v1/payment/escrows/{id}/transactions`| Bearer (Any) | Path: `id` (UUID) | Full ledger transaction entries |

---

### 5.9 Notification Service (Port 8009)
*Source:* [`services/notification-service/app/api/routes/notifications.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/notification-service/app/api/routes/notifications.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/notifications` | Bearer (Any) | Query: `unread_only` (bool), `limit` | `items: [{"id", "title", "message", "is_read", "created_at"}]`, `total_unread` |
| `POST` | `/api/v1/notifications/{id}/read` | Bearer (Any) | Path: `id` (UUID) | Updated notification with `is_read: true` |
| `POST` | `/api/v1/notifications/read-all` | Bearer (Any) | None | `marked_count` |
| `GET` | `/api/v1/notifications/preferences` | Bearer (Any) | None | In-app enabled, email enabled, muted event types |
| `PUT` | `/api/v1/notifications/preferences` | Bearer (Any) | `in_app_enabled`, `email_enabled`, `muted_event_types` | Updated preference object |
| `POST` | `/api/v1/notifications/events` | Internal / Admin | `user_id`, `event_type`, `title`, `message`, `send_email` | Ingested notification result |
| `WS` | `/api/v1/notifications/ws` | WebSocket Auth | Query: `?token=<jwt>` OR in-band auth | Realtime notification events broadcast |

---

### 5.10 Admin Service (Port 8010)
*Source:* [`services/admin-service/app/api/routes/admin.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/admin-service/app/api/routes/admin.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/admin/users` | Bearer (`ADMIN`)| Query: `page`, `page_size`, `role` | Paginated platform users list |
| `POST` | `/api/v1/admin/users/{id}/suspend` | Bearer (`ADMIN`)| `reason` | Suspension confirmation and revoked token count |
| `POST` | `/api/v1/admin/users/{id}/restore` | Bearer (`ADMIN`)| `reason` | Restoration confirmation |
| `GET` | `/api/v1/admin/projects` | Bearer (`ADMIN`)| Query: `page`, `page_size`, `status` | Platform-wide projects inspection list |
| `GET` | `/api/v1/admin/audit-logs` | Bearer (`ADMIN`)| Query: `service_name`, `project_id`, `limit` | Paginated system audit logs |
| `POST` | `/api/v1/admin/reports` | Bearer (`ADMIN`)| `target_type`, `target_id`, `reason` | Created moderation case |
| `GET` | `/api/v1/admin/reports` | Bearer (`ADMIN`)| Query: `status` | List of moderation reports |
| `POST` | `/api/v1/admin/reports/{id}/resolve`| Bearer (`ADMIN`)| `resolution`, `action_taken` | Resolved moderation report |
| `GET` | `/api/v1/admin/actions` | Bearer (`ADMIN`)| Query: `limit` | Administrative audit action trail |

---

### 5.11 Audit Service (Port 8011)
*Source:* [`services/audit-service/app/api/routes/audit.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/audit-service/app/api/routes/audit.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/audit/events` | Internal / Admin | `service_name`, `actor_id`, `action`, `resource_id`, `metadata` | Created immutable audit log record |
| `GET` | `/api/v1/audit/events` | Bearer (Any) | Query: `service_name`, `actor_id`, `action`, `limit`, `offset` | Filtered audit log list |
| `GET` | `/api/v1/audit/projects/{id}` | Bearer (Any) | Path: `id` (UUID), Query: `limit` | Project audit event trail |

---

### 5.12 Observability Service (Port 8012)
*Source:* [`services/observability-service/app/api/routes/observability.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/observability-service/app/api/routes/observability.py)

| Method | Full Gateway Path | Auth / Role Needed | Request Body Fields | Response Key Fields |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/observability/services` | Bearer (`ADMIN`)| None | Live health check status of all 12 services + DB |
| `POST` | `/api/v1/observability/telemetry` | Internal / Admin | `service_name`, `metric_name`, `value`, `tags` | Ingested metric record |
| `GET` | `/api/v1/observability/metrics` | Bearer (`ADMIN`)| Query: `service_name` | Aggregated p50/p95/p99 latency & counts |
| `GET` | `/api/v1/observability/errors` | Bearer (`ADMIN`)| Query: `service_name`, `limit` | Recent sanitized error logs |

---

## 6. Realtime Communication (WebSocket & Kafka)

### 6.1 WebSocket Endpoint Specifications
The API Gateway forwards WebSocket traffic to `notification-service`.

*Source:* [`api-gateway/app/routes/proxy.py:83-140`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/routes/proxy.py#L83-L140), [`services/notification-service/app/api/routes/notifications.py:58-134`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/notification-service/app/api/routes/notifications.py#L58-L134)

* **Public WebSocket URLs:**
  * `ws://localhost:8000/notifications/ws`
  * `ws://localhost:8000/ws/events`
  * `ws://localhost:8000/api/v1/notifications/ws`
  * `ws://localhost:8000/api/v1/ws/events`
* **Authentication Handshake (Three Methods Supported):**
  1. *Query Parameter:* Connect with `ws://localhost:8000/notifications/ws?token=<ACCESS_TOKEN>`
  2. *Header:* Standard `Authorization: Bearer <ACCESS_TOKEN>`
  3. *In-Band JSON Message:* If no header/query is given, the server allows a 15-second grace period for the frontend to send:
     ```json
     { "type": "auth", "token": "<ACCESS_TOKEN>" }
     ```
  * If authentication fails or token is invalid, the server immediately closes the socket with standard WebSocket code `1008` (Policy Violation).
* **Handshake Acknowledgment:**
  On successful authentication, the server emits:
  ```json
  {
    "type": "auth.ok",
    "event": "connected",
    "user_id": "c1f7b8c2-2849-4177-bb89-7cf1f7823f66",
    "role": "FREELANCER"
  }
  ```
* **Heartbeat / Keep-Alive:**
  * Client sends: `{"type": "ping"}`
  * Server responds: `{"type": "pong", "event": "pong"}`
* **Live Server Event Payload (Pushed to Client):**
  Whenever a platform notification is generated for the authenticated user:
  ```json
  {
    "event": "notification.created",
    "data": {
      "id": "e2a6d71b-3f41-47fa-8ea2-1209b5a8e0f1",
      "user_id": "c1f7b8c2-2849-4177-bb89-7cf1f7823f66",
      "event_type": "project.assigned",
      "title": "You have been assigned to project!",
      "message": "Project Owner selected you for Payments Webhook Fix.",
      "resource_type": "project",
      "resource_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "is_read": false,
      "created_at": "2026-11-17T12:05:00Z"
    }
  }
  ```

### 6.2 Kafka Event Topics Useful to UI & Background Sync
*Source:* [`services/identity-service/app/core/kafka_producer.py:77`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/core/kafka_producer.py#L77), [`services/project-service/app/core/kafka_producer.py:77`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/core/kafka_producer.py#L77), [`services/payment-service/app/core/kafka_producer.py:77`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/payment-service/app/core/kafka_producer.py#L77)

| Kafka Topic Name | Producing Service | Event Types (`event_type`) | Purpose / Impact on Frontend State |
| :--- | :--- | :--- | :--- |
| `codebridge.auth.events` | `identity-service` | `user.registered`, `user.login` | Triggers onboarding & login welcome notifications |
| `codebridge.project.events`| `project-service` | `project.created`, `project.assigned`, `project.completed` | Updates project lists and triggers freelancer workspace invites |
| `codebridge.payment.events`| `payment-service` | `escrow.funded`, `escrow.released`, `escrow.refunded` | Updates escrow balance cards and unlocks milestone deliveries |

---

## 7. Data Vocabulary & Enums

Below are the exact enum string values as persisted in the database and returned over JSON APIs. Frontend UI dropdowns, badges, and filters must use these exact values.

### 7.1 Platform Roles (`UserRole`)
*Source:* [`services/identity-service/app/models/user.py:20-26`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/models/user.py#L20-L26)
* `"OWNER"`
* `"FREELANCER"`
* `"ADMIN"`

### 7.2 Freelancer Availability (`AvailabilityStatus`)
*Source:* [`services/identity-service/app/models/freelancer_profile.py:20-26`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/models/freelancer_profile.py#L20-L26)
* `"AVAILABLE"`
* `"BUSY"`
* `"UNAVAILABLE"`

### 7.3 Project Lifecycle Status (`ProjectStatus`)
*Source:* [`services/project-service/app/models/project.py:30-39`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/models/project.py#L30-L39)
* `"OPEN"` — Published by owner, open for proposals/discovery
* `"ASSIGNED"` — Owner has assigned a verified freelancer
* `"IN_PROGRESS"` — Freelancer has started work in sandbox
* `"CHANGES_REQUESTED"` — Owner reviewed submission and requested updates
* `"COMPLETED"` — Solution approved and verified
* `"CANCELLED"` — Cancelled by owner prior to active work

### 7.4 Escrow & Payment Status (`EscrowStatus`)
*Source:* [`services/payment-service/app/models/payment.py:29-38`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/payment-service/app/models/payment.py#L29-L38)
* `"CREATED"` — Escrow record initialized
* `"FUNDED"` — Funds deposited and locked
* `"HELD"` — Funds held pending milestone review
* `"RELEASE_PENDING"` — Approval granted, settlement initiating
* `"RELEASED"` — Funds disbursed to freelancer
* `"REFUND_REQUESTED"` — Dispute or cancellation initiated
* `"REFUNDED"` — Funds returned to owner
* `"CANCELLED"` — Cancelled without charges

### 7.5 Submission Lifecycle (`SubmissionStatus`)
*Source:* [`services/review-service/app/models/submission.py:27-37`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/review-service/app/models/submission.py#L27-L37)
* `"DRAFT"`
* `"SUBMITTED"`
* `"UNDER_REVIEW"`
* `"CHANGES_REQUESTED"`
* `"APPROVED"`
* `"REJECTED"`
* `"WITHDRAWN"`

### 7.6 Review Decisions (`ReviewDecision`)
*Source:* [`services/review-service/app/models/review.py:19-26`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/review-service/app/models/review.py#L19-L26)
* `"PENDING"`
* `"APPROVED"`
* `"CHANGES_REQUESTED"`
* `"REJECTED"`

### 7.7 Workspace Statuses
*Source:* [`services/workspace-service/app/models/workspace.py`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/workspace-service/app/models/workspace.py), [`services/workspace-service/app/api/routes/task_workspaces.py:105`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/workspace-service/app/api/routes/task_workspaces.py#L105)
* Formal container model: `"PENDING"`, `"PROVISIONING"`, `"READY"`, `"RUNNING"`, `"STOPPED"`, `"EXPIRED"`, `"DESTROYED"`
* Task workspace contract: `"running"`, `"stopped"`

---

## 8. GAP Table: React Frontend Needs vs Backend Reality

The table below cross-references each capability required by modern frontend UI flows with the concrete backend implementation.

| Needed Capability | Backend Endpoint or NOT FOUND | Differences (Path, Casing, Field Names, Enum Values, Auth) | Where in the Code |
| :--- | :--- | :--- | :--- |
| **Register** (`{email, password, displayName, role owner\|freelancer}`) | `POST /api/v1/auth/register` | Database uses `full_name` and uppercase `OWNER`\|`FREELANCER`. Pydantic preprocessor aliases `displayName` and uppercases lowercase roles. Password requires 6+ chars. | [`services/identity-service/app/api/routes/auth.py:36-74`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L36-L74), [`app/schemas/auth.py:20-65`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/auth.py#L20-L65) |
| **Login** | `POST /api/v1/auth/login` | Sets `refresh_token` httpOnly cookie (7 days) and returns both snake_case and camelCase tokens (`accessToken`, `refreshToken`, `expiresIn`). | [`services/identity-service/app/api/routes/auth.py:77-122`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L77-L122) |
| **Refresh by cookie** | `POST /api/v1/auth/refresh` | Reads cookie `refresh_token` (or `mock_rt`) or request body `{ "refreshToken": "..." }`. Issues rotated cookie and JSON. | [`services/identity-service/app/api/routes/auth.py:124-172`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L124-L172) |
| **Logout** | `POST /api/v1/auth/logout` | Requires `Authorization: Bearer <access_token>`. Clears `refresh_token` cookie and revokes token family. | [`services/identity-service/app/api/routes/auth.py:174-226`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/auth.py#L174-L226) |
| **Me** (`id, email, displayName, role, status, createdAt, onboardingCompleted`) | `GET /api/v1/users/me` & `GET /api/v1/auth/me` | Canonical response includes `id`, `email`, `displayName`, `role` (uppercase), `status` (`"active"`), `onboardingCompleted` (`true`), `created_at` (snake_case). Frontend expecting `createdAt` must map from `created_at`. | [`services/identity-service/app/api/routes/users.py:16-25`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/users.py#L16-L25), [`app/schemas/user.py:13-39`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/schemas/user.py#L13-L39) |
| **Owner profile save** (`ownerType, organizationName, roleTitle, timezone, primaryStack, typicalBlocker, defaultBudgetRange, preferredVerificationMode`) | `PUT /api/v1/users/me/owner-profile` & `PATCH /api/v1/users/me/owner-profile` | Accepts free-form JSON. If `organizationName` is passed, updates user `full_name`. Returns `{"profile": body, "onboardingCompleted": true}`. The specific extended fields are stored transiently. | [`services/identity-service/app/api/routes/users.py:28-48`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/users.py#L28-L48) |
| **Owner profile get** | **NOT FOUND** | Dedicated endpoint `GET /api/v1/users/me/owner-profile` does NOT exist. Caller must rely on `GET /api/v1/users/me` or `GET /api/v1/profile`. (Searched: `identity-service/app/api/routes/users.py`, `profile.py`, `auth.py`). | Files searched: `users.py`, `profile.py`, `auth.py` |
| **Freelancer profile save** (`headline, experience, bio, skills, supportedStacks, debuggingSpecialties, availability, minBudget, githubUsername, portfolioUrl`) | `PUT /api/v1/talent/profiles/me` & `PATCH /api/v1/freelancers/me` | Two options: `PUT /talent/profiles/me` accepts the full frontend onboarding dictionary and returns `{profile, onboardingCompleted: true}`. Formal `PATCH /freelancers/me` updates SQL columns `bio`, `skills`, `experience_years`, `availability`. | [`services/identity-service/app/api/routes/users.py:51-73`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/users.py#L51-L73), [`app/api/routes/freelancers.py:55-81`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/freelancers.py#L55-L81) |
| **Projects: Create** (`title, description, stacks, budget, urgency, repo URL`) | `POST /api/v1/projects` | Differences: 1. `stacks` must be passed as `required_skills` (or `tags`). 2. `urgency` does not exist; backend requires `deadline` (date, default: now + 30 days). 3. `repo URL` is decoupled and connected via separate route `POST /projects/{id}/github/connect`. | [`services/project-service/app/api/routes/projects.py:35-81`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/projects.py#L35-L81), [`app/schemas/project.py:77-158`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/schemas/project.py#L77-L158) |
| **Projects: List mine** | `GET /api/v1/projects` | Role-scoped automatically: an authenticated `OWNER` calling `GET /projects` receives only their own projects. Specific path `/projects/mine` does NOT exist. | [`services/project-service/app/api/routes/projects.py:83-145`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/projects.py#L83-L145) |
| **Projects: Get one** | `GET /api/v1/projects/{id}` | Requires UUID. Returns complete project object with requirement spec, budget, deadline, and assignments. | [`services/project-service/app/api/routes/projects.py:147-185`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/projects.py#L147-L185) |
| **Projects: Recommended freelancers** | **NOT FOUND** | Automated recommendation matching endpoint `GET /projects/{id}/recommended-freelancers` does NOT exist. Frontend must query `GET /api/v1/freelancers?skill=...` manually. | Files searched: `project-service/app/api/routes/projects.py`, `assignments.py`, `freelancers.py` |
| **Projects: Freelancer public profile** | `GET /api/v1/freelancers/{id}` | Requires UUID. Returns public biography, skill tags, years of experience, and availability status. | [`services/identity-service/app/api/routes/freelancers.py:83-103`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/freelancers.py#L83-L103) |
| **Projects: Shortlist** | **NOT FOUND** | No shortlisting or bookmarking entities exist in `project-service`. Direct assignment is supported via `POST /api/v1/projects/{id}/select-freelancer`. | Files searched: `services/project-service/app/api/routes/projects.py`, `assignments.py` |
| **Payments: Escrow state per task/project** | `GET /api/v1/payment/escrow/{task_id}` & `GET /api/v1/payment/projects/{project_id}` | Per-task returns `{"status": "funded", "reward": 4500.0, "currency": "USD"}`. Per-project returns list of formal `EscrowPaymentResponse` records with uppercase states (`FUNDED`, `HELD`, `RELEASED`). | [`services/payment-service/app/api/routes/payment.py:182-194, 224-237`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/payment-service/app/api/routes/payment.py#L182-L194) |
| **Payments: Summary** (`held, released, pending`) | `GET /api/v1/payment/summary` (and `/payments/summary`) | Consolidated payload returning `held`, `pendingRelease`, `released`, `total_spent`, `total_escrow`, `currency`, `items`. Matches frontend expectations. | [`services/payment-service/app/api/routes/payment.py:36-72`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/payment-service/app/api/routes/payment.py#L36-L72) |
| **Work: Freelancer tasks** | `GET /api/v1/tasks/mine` | Returns `{"items": [{"id", "title", "projectTitle", "status": "in_progress"\|"in_review"\|"completed", "reward", "dueAt"}]}`. | [`services/project-service/app/api/routes/tasks.py:50-74`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/tasks.py#L50-L74) |
| **Work: Workspace start, stop, reset, status** | `GET|POST /api/v1/workspaces/{task_id}[/start\|/stop\|/reset]` | Status: `GET /workspaces/{task_id}`. Start: `POST /workspaces/{task_id}/start`. Stop: `POST /workspaces/{task_id}/stop`. Reset: `POST /workspaces/{task_id}/reset`. | [`services/workspace-service/app/api/routes/task_workspaces.py:119-156`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/workspace-service/app/api/routes/task_workspaces.py#L119-L156) |
| **Work: Files list, read, and write** | `GET|PUT /api/v1/workspaces/{task_id}/files[/content]` | List: `GET /workspaces/{task_id}/files`. Read: `GET /workspaces/{task_id}/files/content?path=...`. Write: `PUT /workspaces/{task_id}/files/content` with body `{path, content}`. | [`services/workspace-service/app/api/routes/task_workspaces.py:158-212`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/workspace-service/app/api/routes/task_workspaces.py#L158-L212) |
| **Work: Test runs and results** | `POST /api/v1/submissions/runs` & `GET /api/v1/submissions/runs/{run_id}` | Trigger: `POST /submissions/runs` with `{taskId}` -> returns `{runId}`. Polling results: `GET /submissions/runs/{run_id}` -> returns test status and results array. | [`services/review-service/app/api/routes/submissions.py:76-136`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/review-service/app/api/routes/submissions.py#L76-L136) |
| **Work: Submission create and status** | `POST /api/v1/submissions` & `GET /api/v1/submissions/current` | Submit solution: `POST /submissions` with `{taskId, notes}` -> returns `{submissionId, status: "in_review"}`. Status: `GET /submissions/current?taskId=...` -> returns submission note and status. | [`services/review-service/app/api/routes/submissions.py:138-183`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/review-service/app/api/routes/submissions.py#L138-L183) |
| **Work: AI / Code-Context for task** | `GET /api/v1/ai/context/{task_id}` | Returns `{"summary", "findings": [...], "relevantFiles": [{"path", "score", "reason"}], "approach": [...]}`. Matches frontend contract. | [`services/code-context-service/app/api/routes/ai_context.py:13-59`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/code-context-service/app/api/routes/ai_context.py#L13-L59) |
| **Admin: Users list and service health** | `GET /api/v1/admin/users` & `GET /api/v1/observability/services` | Users list: `GET /admin/users` (requires `ADMIN` role). Service health: `GET /observability/services` (returns health status of all 12 services). | [`services/admin-service/app/api/routes/admin.py:34-50`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/admin-service/app/api/routes/admin.py#L34-L50), [`services/observability-service/app/api/routes/observability.py:30-39`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/observability-service/app/api/routes/observability.py#L30-L39) |
| **Notifications: List and live events** | `GET /api/v1/notifications` & `WS /notifications/ws` | REST: `GET /notifications` returns unread/recent items. Realtime: WebSocket at `/notifications/ws` with `?token=<jwt>` receives live push events `{event: "notification.created", data: {...}}`. | [`services/notification-service/app/api/routes/notifications.py:58-148`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/notification-service/app/api/routes/notifications.py#L58-L148) |

---

## 9. Top 10 Mismatches (Ordered by Potential to Break UI)

Below are the 10 most critical architectural and schema differences between common React frontend assumptions and the CodeBridge backend.

### 1. Project Creation Decoupled from GitHub Repository URL (High Severity)
* **The Break:** Frontend wizards typically collect `title`, `description`, `budget`, and a `gitRepoUrl` in a single "Create Project" form.
* **Backend Reality:** `POST /api/v1/projects` ignores or rejects repository URLs ([`services/project-service/app/schemas/project.py:77-158`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/schemas/project.py#L77-L158)). GitHub linking requires a separate OAuth handshake (`GET /api/v1/github/oauth/authorize?project_id=...`) followed by calling `POST /api/v1/projects/{project_id}/github/connect` with `{github_repo_id, repo_name}`.
* **Frontend Fix:** Split project creation into a 2-step wizard: Step 1 posts to `/projects` to acquire a `project_id`; Step 2 triggers the GitHub OAuth repository connection flow.

### 2. Missing Recommended Freelancers & Shortlisting Endpoints (High Severity)
* **The Break:** Frontend project management screens attempting to fetch `GET /api/v1/projects/{id}/recommended-freelancers` or manage a shortlist receive HTTP 404 NOT FOUND.
* **Backend Reality:** No recommendation engine endpoint or shortlist database table exists.
* **Frontend Fix:** The frontend must use the public directory endpoint `GET /api/v1/freelancers?skill=<stack>` to search freelancers, and directly trigger `POST /api/v1/projects/{id}/select-freelancer` when assigning.

### 3. Role Casing Mismatch in Stored JWT & User Objects (High Severity)
* **The Break:** Frontend guards frequently use lowercase checks: `if (user.role === 'owner')` or `if (user.role === 'freelancer')`.
* **Backend Reality:** Database column and JWT claims strictly store uppercase strings: `"OWNER"`, `"FREELANCER"`, `"ADMIN"` ([`services/identity-service/app/models/user.py:20-26`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/models/user.py#L20-L26)).
* **Frontend Fix:** Use case-insensitive role comparisons in React auth context: `user.role?.toUpperCase() === 'OWNER'`.

### 4. WebSocket Authentication Handshake Failure (High Severity)
* **The Break:** Standard browser `new WebSocket("ws://localhost:8000/notifications/ws")` does not permit passing an `Authorization: Bearer <token>` header in JavaScript.
* **Backend Reality:** If no token is provided, the backend closes the connection with code `1008 Policy Violation` within 15 seconds ([`services/notification-service/app/api/routes/notifications.py:70-84`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/notification-service/app/api/routes/notifications.py#L70-L84)).
* **Frontend Fix:** Pass the JWT token in the query string: `new WebSocket('ws://localhost:8000/notifications/ws?token=' + accessToken)` or immediately send an in-band JSON message `ws.send(JSON.stringify({ type: 'auth', token: accessToken }))`.

### 5. Missing Dedicated Owner Profile GET Route (Medium-High Severity)
* **The Break:** React onboarding forms re-fetching saved owner configuration via `GET /api/v1/users/me/owner-profile` receive HTTP 404 NOT FOUND.
* **Backend Reality:** While `PUT /api/v1/users/me/owner-profile` exists to save onboarding data, there is no corresponding GET sub-route ([`services/identity-service/app/api/routes/users.py:28-48`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/identity-service/app/api/routes/users.py#L28-L48)).
* **Frontend Fix:** Fetch user identity from `GET /api/v1/users/me` or profile data from `GET /api/v1/profile`.

### 6. Idempotency-Key Header Required on Escrow Transactions (Medium Severity)
* **The Break:** React payment and escrow actions (`/fund`, `/release`, `/refund`) omitting the `Idempotency-Key` header will bypass double-click deduplication.
* **Backend Reality:** Payment endpoints explicitly declare `idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")` and reject replayed transactions with HTTP 409 ([`services/payment-service/app/api/routes/payment.py:83, 101, 135, 153`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/payment-service/app/api/routes/payment.py#L83)).
* **Frontend Fix:** Generate a UUID on form submit and attach `headers: { 'Idempotency-Key': crypto.randomUUID() }` to every escrow mutation.

### 7. Global Error Envelope Structure (Medium Severity)
* **The Break:** Code written against default FastAPI endpoints expects error messages in `response.data.detail`.
* **Backend Reality:** The API Gateway intercepts all 4xx/5xx responses and wraps them in `{"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}` ([`api-gateway/app/core/exceptions.py:154-174`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/core/exceptions.py#L154-L174)).
* **Frontend Fix:** Configure Axios/fetch interceptor to parse `error.response?.data?.error?.message || error.response?.data?.detail`.

### 8. Strict UUID Format Validation on Project & User Routes (Medium Severity)
* **The Break:** Passing non-UUID strings (e.g. slug strings or mock IDs like `"proj-123"`) to `/api/v1/projects/{project_id}` causes immediate HTTP 422 Unprocessable Entity.
* **Backend Reality:** FastAPIRoute signatures type-hint `project_id: uuid.UUID`. Path parameters are validated strictly as canonical 36-character UUIDs ([`services/project-service/app/api/routes/projects.py:165`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/api/routes/projects.py#L165)).
* **Frontend Fix:** Ensure client state passes true UUID strings for all project and user entity lookups.

### 9. Rate Limiting Enforced with Sliding Window in Redis (Medium Severity)
* **The Break:** Rapid UI polling loops on authentication or task status endpoints can encounter unexpected HTTP 429 errors.
* **Backend Reality:** Gateway rate limiting enforces 20 requests/min on auth routes (`/login`, `/register`) and 120 requests/min on general routes ([`api-gateway/app/middleware/rate_limit.py:48-54`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/api-gateway/app/middleware/rate_limit.py#L48-L54)).
* **Frontend Fix:** Use exponential backoff when retrying and adhere to `Retry-After` response headers. Avoid tight polling loops; prefer WebSocket notifications for live updates.

### 10. Date Formatting and Deadline Validation (Low-Medium Severity)
* **The Break:** Sending ISO datetime timestamps (e.g. `2026-12-20T18:30:00Z`) for project `deadline` will fail validation.
* **Backend Reality:** Project `deadline` is typed as a pure SQL `date` object (`YYYY-MM-DD`). Passing past dates is rejected with `ValueError("deadline cannot be in the past.")` ([`services/project-service/app/schemas/project.py:70-74`](file:///c:/Users/acer/OneDrive/Desktop/codebridge%20backend/codebridge-backend/services/project-service/app/schemas/project.py#L70-L74)).
* **Frontend Fix:** Format deadline fields as `YYYY-MM-DD` strings before submitting create/update payloads.
