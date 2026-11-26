# CodeBridge Edge Load Balancing Architecture

> **Component:** Edge Reverse Proxy & Multi-Node Gateway Load Balancer  
> **Implementation:** High-Performance Nginx Alpine + Multi-Replica FastAPI Gateway  
> **Status:** Production-Ready  

---

## 1. Executive Summary

CodeBridge implements an enterprise-grade **Two-Tier Load Balancing Architecture**:
1. **Tier 1 (Edge Reverse Proxy & Load Balancer):** An optimized, non-blocking Nginx proxy listening on ports `80` (HTTP), `8000` (Gateway compatibility alias), and `8080` (Secondary alias). It terminates client requests, enforces rate-limiting zones, performs gzip compression, and balances traffic across backend gateway replicas.
2. **Tier 2 (Gateway Replicas):** Scaled FastAPI API Gateway instances (`api-gateway` and `api-gateway-replica`), sharing distributed state via Upstash/Redis, routing requests down to the 12 domain microservices over persistent HTTPX connection pools.

```
                         ┌─────────────────────────────────────────┐
                         │   Client / Browser / Frontend Apps      │
                         └────────────────────┬────────────────────┘
                                              │ Ports: 80 / 8000 / 8080
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │    CodeBridge Nginx Load Balancer       │
                         │       (Algorithm: least_conn)           │
                         └──────────────┬──────────────────┬───────┘
                                        │                  │
                API / Auth / Microservices                 │ Root / Frontend SPAs
                                        │                  ▼
                                        │         ┌───────────────────────┐
                                        │         │ Frontend Container    │
                                        │         │ (frontend:3000)       │
                                        │         └───────────────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 ▼                                             ▼
     ┌───────────────────────┐                     ┌───────────────────────┐
     │  api-gateway (Node 1) │                     │  api-gateway-replica  │
     │     (Port :8000)      │                     │     (Port :8000)      │
     └───────────┬───────────┘                     └───────────┬───────────┘
                 │                                             │
                 └──────────────────────┬──────────────────────┘
                                        ▼
                  ┌───────────────────────────────────────────┐
                  │   Shared Redis Cache / Rate Limiting      │
                  └─────────────────────┬─────────────────────┘
                                        ▼
                  ┌───────────────────────────────────────────┐
                  │ 12 Domain Microservices (8001 - 8012)     │
                  └───────────────────────────────────────────┘
```

---

## 2. Load Balancing Algorithm & Configuration

### Algorithm: `least_conn`
Instead of standard Round Robin (which blindly cycles requests), CodeBridge uses **Least Connections (`least_conn`)**.
- Incoming requests are routed to the API Gateway node with the lowest number of active concurrent requests.
- If Node 1 is processing a heavy code context query or workspace snapshot, subsequent requests automatically flow to Node 2 without bottlenecking.

### Upstream Definition
```nginx
upstream api_gateway_cluster {
    least_conn;
    server api-gateway:8000 max_fails=3 fail_timeout=10s;
    server api-gateway-replica:8000 max_fails=3 fail_timeout=10s;
    keepalive 64;
}
```

### High-Availability Failover (`proxy_next_upstream`)
If an upstream node encounters an error (`http_502`, `http_503`, `http_504` or timeout), the Load Balancer automatically retries the request against the alternate node in milliseconds:
```nginx
proxy_next_upstream error timeout http_502 http_503 http_504;
proxy_next_upstream_tries 3;
```

---

## 3. Performance & Speed Optimizations

| Optimization | Configuration | Impact |
| :--- | :--- | :--- |
| **Connection Pooling** | `keepalive 64;` + `proxy_http_version 1.1;` | Eliminates TCP 3-way handshake latency on every request |
| **Gzip Compression** | `gzip_comp_level 5;` | Compresses JSON, text, and code context responses by up to 80% |
| **Non-blocking Socket I/O** | `sendfile on; tcp_nopush on; tcp_nodelay on;` | Enables kernel zero-copy and reduces packet fragmentation |
| **Buffer Tuning** | `client_max_body_size 100M; proxy_buffer_size 32k;` | Allows large workspace zip uploads without disk thrashing |
| **Multi-Worker Concurrency** | `worker_processes auto; worker_connections 8192;` | Handles up to 16,000+ concurrent connections per core |
| **DDoS Rate Limiting** | `limit_req_zone` (150r/s API, 25r/s Auth) | Drops malicious traffic at the edge before hitting Python runtime |

---

## 4. Frontend Microservices Integration

When deploying dockerized frontend microservices:
1. Run your frontend container with container name `frontend` on port `3000` attached to `codebridge-net`.
2. The Load Balancer automatically proxies root traffic (`/`) to `http://frontend:3000` with WebSocket support (`Upgrade` / `$connection_upgrade`).
3. If the frontend container is stopped or still booting, the Load Balancer cleanly intercepts the connection and returns the **CodeBridge Edge Gateway Status Dashboard** (`/index.html`) rather than an ugly raw error page.

---

## 5. Verification & Health Monitoring Endpoints

You can demonstrate and test the Load Balancer using any browser or HTTP client:

1. **Load Balancer Direct Health Probe:**
   ```bash
   curl http://localhost/lb-health
   # Returns: {"status":"healthy","service":"codebridge-load-balancer","algorithm":"least_conn",...}
   ```

2. **API Health through Load Balancer (Port 8000 or 80):**
   ```bash
   curl http://localhost:8000/health
   # Returns: {"status":"healthy","service":"api-gateway","version":"1.0.0",...}
   ```

3. **Interactive Swagger Documentation:**
   Open `http://localhost:8000/docs` or `http://localhost/docs` in your browser.

4. **Direct Gateway Node Diagnostics (Bypassing Load Balancer):**
   - Node 1: `http://localhost:8081/health`
   - Node 2: `http://localhost:8082/health`

---

## 6. How to Deploy on AWS

When you are ready to deploy to AWS:
1. **AWS Application Load Balancer (ALB):**
   - Create an internet-facing ALB listening on `80` and `443` (with ACM SSL certificate).
   - Create a Target Group for the Gateway ECS Tasks.
2. **ECS Fargate:**
   - Deploy `api-gateway` as an ECS Service with `desired_count: 2` (or Auto-Scaling from 2 to 10 based on CPU/Memory).
   - Deploy Frontend container tasks under a secondary Target Group routed by path (`/*` $\rightarrow$ Frontend, `/api/*` $\rightarrow$ Gateway).
