
<div align="center">

# ◆ Barcode Server

**A production-grade REST API & CLI for storing products, barcodes, and images.**

Fast · Secure · Self-hosted · Zero-config

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-2.x-black)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)](LICENSE)
[![Status](https://img.shields.io/badge/status-stable-brightgreen)]()
[![PRs](https://img.shields.io/badge/PRs-welcome-blueviolet)]()

[▸ Quick Start](#-quick-start) &nbsp;·&nbsp; [▸ Features](#-features) &nbsp;·&nbsp; [▸ API Reference](#-api-reference) &nbsp;·&nbsp; [▸ FAQ](#-faq) &nbsp;·&nbsp; [▸ Contributing](#-contributing)

</div>

---

## ◈ What is this?

A lightweight, self-hosted server that maps **barcodes → products → images**. It exposes a REST API and a CLI so you can add, look up, search, update, and delete product records — all backed by simple CSV shards and a JSON index.

**Perfect for:**

- ▸ Inventory management systems
- ▸ Mobile shopping apps (barcode scanners)
- ▸ Point-of-sale (POS) software
- ▸ Product lookup services
- ▸ Warehouse tools

**Not intended for:**

- ✕ Multi-tenant SaaS (single-writer design)
- ✕ Distributed deployments (no shared state)
- ✕ Terabyte-scale data (use PostgreSQL instead)

---

## ▸ Quick Start

**Get running in 60 seconds.**

```bash
# 1. Clone & install
git clone https://github.com/NRXQuantum/barcode-server.git
cd barcode-server
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Set your first API key
export BARCODE_API_KEY="my-super-secret-key-change-me"

# 3. Run
python barcode_server.py
```

Server is live at http://localhost:5000

Test it:

```bash
# Add a product
curl -X POST http://localhost:5000/api/add \
  -H "X-API-Key: my-super-secret-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"barcode":"1234567890","name":"Coca Cola 500ml","image":"https://example.com/coke.jpg"}'

# Look it up (no auth required)
curl http://localhost:5000/api/lookup/1234567890

# See server stats
python barcode_server.py --stats
```

---

▤ Table of Contents

<details>
<summary><b>Click to expand full navigation</b></summary>

Getting Started

· What is this?
· Quick Start
· Requirements & Installation
· Running the Server

Understanding the System

· Architecture Overview
· Storage Model
· Image Delivery Modes
· First Startup Behavior

Using the Server

· CLI Commands
· API Reference
· Common Workflows
· Authentication
· Rate Limits

Operations

· Configuration
· Security Model
· Metrics & Health
· Deployment
· Backup & Recovery

Reference

· Error Codes
· FAQ
· Troubleshooting
· Contributing

</details>

---

▣ Features

Core

Symbol Feature Description
◆ Public Lookup Anyone can query barcodes — no auth needed
▣ Multi-Product One barcode can hold multiple products
▤ Sharded CSV Storage Auto-rotates at 10,000 rows per shard
◎ In-Memory Index Sub-millisecond lookups from JSON index
✦ Protected Writes Add/update/delete require API key

Advanced

Symbol Feature Description
◈ Hybrid Images 302 redirect by default; proxy fallback
▤ Pagination /api/all?page=1&per_page=50
▸ Search Match by name or barcode
▣ Bulk Operations Up to 100 items per batch
■ Safe Delete Index-based, audit-logged, confirm header
◎ Health & Stats JSON endpoints for monitoring
✦ CSV Injection Guard Blocks + - = @ prefixes
✦ IPv4 + IPv6 Safe Rejects private/reserved addresses

---

▤ Architecture Overview

```
┌─────────────┐       ┌──────────────────────┐       ┌─────────────────┐
│   Client    │──────▶│  Flask API Server    │──────▶│  CSV Shards     │
│  (App/Web)  │◀──────│  (barcode_server.py) │◀──────│  + JSON Index   │
└─────────────┘       └──────────────────────┘       └─────────────────┘
                             │
                             │ image mode = redirect
                             ▼
                      ┌──────────────────┐
                      │  External Image  │
                      │      Source      │
                      └──────────────────┘
```

Data flow:

1. Add — Validate image URL → Append to active CSV shard → Update JSON index → Cache in background
2. Lookup — Check memory cache → Fall back to in-memory index → Return list of products
3. Image — Return 302 to original URL (fast) or stream via proxy (fallback)
4. Delete — Verify API key + confirm header → Remove indices → Rewrite shards → Log to audit

---

▤ Requirements & Installation

Minimum: Python 3.8+

```bash
git clone https://github.com/NRXQuantum/barcode-server.git
cd barcode-server

python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install --upgrade pip
pip install -r requirements.txt
```

Dependencies:

Package Purpose
flask Web framework
flask-limiter Rate limiting
flask-caching In-memory cache
requests Image URL validation & download
gunicorn Production WSGI server

---

▸ Running the Server

Development

```bash
python barcode_server.py
# → http://localhost:5000
```

Production (Gunicorn)

```bash
gunicorn --workers 2 --bind 0.0.0.0:5000 barcode_server:app
```

Warning — multi-worker setups: Each worker keeps its own cache, metrics, and rate limiter. They do not share state. For multi-worker setups use Redis for cache and rate limits, and a proper database.

Render.com (self-pinging)

```bash
python render.py
```

Pings /api/ every 12 minutes to keep the free instance alive.

---

▤ Storage Model

Directory Layout

```
barcode_data/
├── index.json              # barcode → [products]
├── api_keys.json           # API key registry
├── deletion_audit.log      # every delete (success + failure)
├── my_products_0.csv       # shard (10k rows max)
└── my_products_1.csv       # next shard (auto-created)
```

JSON Index Format

```json
{
  "6281006451865": [
    {
      "name": "Paracetamol 500mg",
      "image": "https://example.com/p.jpg",
      "shard": "my_products_0.csv"
    }
  ]
}
```

CSV Shard Format

```csv
barcode,product_name,image_url
6281006451865,Paracetamol 500mg,https://example.com/p.jpg
```

Rules

Rule Value
Max rows per shard 10,000
Duplicate detection Same barcode + same name
Index location barcode_data/index.json
Audit log Append-only

---

◈ Image Delivery Modes

Two modes are available. The default is redirect.

■ Mode A — Redirect (default, recommended)

```
Client → API: "Give me image for 12345"
API    → Client: "302 → https://source.com/img.jpg"
Client → source.com: "Give me the image"
source.com → Client: [image bytes]
```

· ▸ Near-zero server load
· ▸ Unlimited concurrency
· ▸ Blocked by hotlink-protected sites

■ Mode B — Proxy (fallback)

```
Client → API: "Give me image for 12345 (?proxy=1)"
API    → source.com: "Give me the image"
source.com → API: [image bytes]
API    → Client: [image bytes]
```

· ▸ Works everywhere
· ▸ Uses server bandwidth + RAM

Use proxy when:

· The source blocks hotlinking (Amazon, Flipkart)
· The URL requires authentication headers
· You need to hide the source URL

Switch mode:

```bash
# Per-request
curl "http://localhost:5000/api/lookup/12345/image?proxy=1"

# Global default (edit source)
IMAGE_MODE = 'proxy'
```

---

▸ CLI Commands

All commands run from the repo root.

Add products

```bash
python barcode_server.py --add
```

Interactive prompts: barcode → name → optional image URL.

Edit a product

```bash
python barcode_server.py --edit
```

Select by barcode + index. Press Enter to keep the current value.

List all products

```bash
python barcode_server.py --list
```

Table: barcode | name | image URL.

Show dashboard stats

```bash
python barcode_server.py --stats
```

Colored dashboard: products, images, storage, active shard, API keys.

API key management

```bash
# Add
python barcode_server.py --add-key "NEW_KEY" \
  --name "Android App" \
  --limits "lookup:500,image:20,add:10"

# Remove
python barcode_server.py --remove-key "OLD_KEY"

# List
python barcode_server.py --list-keys
```

---

▸ API Reference

Base URL: http://localhost:5000/api

Endpoint Summary

Method Endpoint Auth Purpose
GET /api/ — API info
GET /api/lookup/<bc> — Get all products
GET /api/lookup/<bc>/image — Get first product's image
POST /api/lookup-batch — Bulk lookup (≤100)
GET /api/all — List all (paginated)
GET /api/search?q=<text> — Search name or barcode
POST /api/add ✦ Add product
POST /api/add-batch ✦ Bulk add (≤100)
PUT /api/update/<bc> ✦ Update by index
DELETE /api/delete/<bc> ✦ Delete indices
GET /api/export ✦ Download CSV ZIP
GET /api/metrics — Server metrics
GET /api/stats — JSON dashboard
GET /api/health — Health check

▸ GET /api/lookup/&lt;barcode&gt;

Public. Returns every product registered under the barcode.

```bash
curl http://localhost:5000/api/lookup/6281006451865
```

```json
{
  "barcode": "6281006451865",
  "products": [
    {
      "name": "Paracetamol 500mg",
      "image": "https://example.com/p.jpg",
      "shard": "my_products_0.csv"
    }
  ]
}
```

Errors: 404 if the barcode is not found.

▸ POST /api/add

Requires X-API-Key.

```bash
curl -X POST http://localhost:5000/api/add \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"barcode":"123","name":"Product","image":"https://..."}'
```

```json
{
  "status": "ok",
  "message": "Product added successfully. Image caching in background.",
  "shard": "my_products_0.csv"
}
```

The image URL is validated first. Duplicate barcode + name combinations are rejected.

▸ POST /api/add-batch

Requires X-API-Key. Up to 100 items per call.

```bash
curl -X POST http://localhost:5000/api/add-batch \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {"barcode":"111","name":"A"},
    {"barcode":"222","name":"B"}
  ]'
```

```json
{
  "added": 2,
  "failed": 0,
  "results": [
    {"index": 0, "status": "added", "barcode": "111"},
    {"index": 1, "status": "added", "barcode": "222"}
  ]
}
```

▸ PUT /api/update/&lt;barcode&gt;

Requires X-API-Key. index is zero-based.

```bash
curl -X PUT http://localhost:5000/api/update/123 \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"index":0,"name":"New Name"}'
```

Omit a field to keep its old value. Both the lookup cache and the image cache are cleared.

▸ DELETE /api/delete/&lt;barcode&gt;

Requires X-API-Key and X-Confirm-Delete: YES-DELETE.

```bash
curl -X DELETE http://localhost:5000/api/delete/123 \
  -H "X-API-Key: YOUR_KEY" \
  -H "X-Confirm-Delete: YES-DELETE" \
  -H "Content-Type: application/json" \
  -d '{"indices":[0,2]}'
```

```json
{
  "status": "ok",
  "deleted": 2,
  "details": [
    {"index": 0, "status": "deleted", "name": "Product A"},
    {"index": 2, "status": "deleted", "name": "Product C"}
  ]
}
```

Safety layers:

1. X-API-Key header required
2. X-Confirm-Delete: YES-DELETE header required
3. indices array mandatory — no "delete all" option exists
4. Rate limit: 5 requests per minute
5. Every delete logged to deletion_audit.log

The barcode itself cannot be deleted — only products under it.

▸ GET /api/search

Public. Searches product names and barcodes with case-insensitive substring matching.

```bash
curl "http://localhost:5000/api/search?q=para&page=1&per_page=20"
```

```json
{
  "query": "para",
  "page": 1,
  "per_page": 20,
  "total_matches": 5,
  "total_pages": 1,
  "items": [
    {
      "barcode": "6281006451865",
      "product_name": "Paracetamol 500mg",
      "image_url": "https://...",
      "shard": "my_products_0.csv"
    }
  ]
}
```

▸ GET /api/all

Public. Flat response when no pagination params are supplied (backward compatible):

```bash
curl http://localhost:5000/api/all
```

Paginated response when page or per_page are supplied:

```bash
curl "http://localhost:5000/api/all?page=1&per_page=50"
```

```json
{
  "page": 1,
  "per_page": 50,
  "total": 356,
  "total_pages": 8,
  "items": []
}
```

▸ POST /api/lookup-batch

Public. Up to 100 barcodes per call.

```bash
curl -X POST http://localhost:5000/api/lookup-batch \
  -H "Content-Type: application/json" \
  -d '["111", "222", "999"]'
```

```json
{
  "111": [{"name": "A", "image": "...", "shard": "..."}],
  "222": null,
  "999": null
}
```

▸ GET /api/health

Public. Cheap health endpoint.

```bash
curl http://localhost:5000/api/health
```

```json
{
  "status": "ok",
  "uptime": "2h 15m 30s",
  "uptime_seconds": 8130,
  "shards": 2,
  "barcodes": 128,
  "active_shard": "my_products_1.csv"
}
```

▸ GET /api/stats

Public. JSON version of the --stats CLI dashboard. Full example in Metrics & Health.

▸ GET /api/metrics

Public. Process-local metrics.

```json
{
  "total_requests": 10,
  "cache_hits": 4,
  "cache_misses": 6,
  "cache_hit_ratio": 40.0,
  "avg_response_time_ms": 12.34,
  "active_shard": "my_products_0.csv",
  "total_entries": 26
}
```

▸ GET /api/export

Requires X-API-Key. Downloads all CSV shards as a ZIP.

```bash
curl -H "X-API-Key: YOUR_KEY" \
  http://localhost:5000/api/export -o all_shards.zip
```

---

◎ Common Workflows

Workflow 1 — Mobile App Integration

Scenario: Your mobile app scans a barcode and shows product info and an image.

```
1. App scans barcode      →  GET /api/lookup/6281006451865
2. API returns product list
3. App displays           →  <img src="https://api.example.com/api/lookup/6281006451865/image">
4. Server returns 302     →  app auto-follows → image loads
```

No SDK needed. Works with <img> tags, Glide, SDWebImage, Flutter Image.network, and React Native.

Workflow 2 — Admin Bulk Import

```bash
# Import 500 products in 5 batches
curl -X POST http://localhost:5000/api/add-batch \
  -H "X-API-Key: ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d @batch1.json   # up to 100 items each
```

Workflow 3 — Removing a Bad Entry

```bash
# 1. Check what's there
curl http://localhost:5000/api/lookup/12345

# 2. Delete index 1 (the second product)
curl -X DELETE http://localhost:5000/api/delete/12345 \
  -H "X-API-Key: ADMIN_KEY" \
  -H "X-Confirm-Delete: YES-DELETE" \
  -H "Content-Type: application/json" \
  -d '{"indices":[1]}'

# 3. Check the audit log
tail barcode_data/deletion_audit.log
```

Workflow 4 — Search & Paginate

```bash
# Find all products with "para" in name or barcode
curl "http://localhost:5000/api/search?q=para&page=1&per_page=50"
```

---

✦ Authentication

Protected endpoints require the X-API-Key header.

Key Record Structure

```json
{
  "name": "Android App",
  "enabled": true,
  "limits": {"lookup": 500, "image": 20, "add": 10}
}
```

Response Matrix

Situation Status Body
Missing key 401 {"error": "Missing X-API-Key header."}
Unknown key 401 {"error": "Invalid API Key."}
Disabled key 403 {"error": "API Key is disabled."}
Delete without confirm header 400 {"error": "Missing or invalid X-Confirm-Delete header."}

Rotating Keys

```bash
# 1. Add new key
python barcode_server.py --add-key "NEW_KEY" --name "App v2"

# 2. Update client to use the new key
# 3. Verify the old key is no longer used (check logs)
# 4. Remove the old key
python barcode_server.py --remove-key "OLD_KEY"
```

---

▸ Rate Limits

Endpoint Anonymous With Key
/api/lookup/<bc> 20/sec Key's lookup (fallback 200/sec)
/api/lookup/<bc>/image 1 per 3 sec Key's image (fallback 5/sec)
/api/add — Key's add (fallback 5/sec)
/api/add-batch — Same as add
/api/update/<bc> — Same as add
/api/delete/<bc> — 5/min
/api/all 30/sec 30/sec
/api/search 30/sec 30/sec
/api/export — 2/min
/api/metrics 10/min 10/min
/api/health 60/min 60/min
/api/stats 30/sec 30/sec

Rate limits use memory:// and are not shared between Gunicorn workers. Use Redis for distributed deployments.

---

▤ Configuration

All constants live in barcode_server.py:

```python
DATA_DIR           = "barcode_data"
INDEX_FILE         = "barcode_data/index.json"
API_KEYS_FILE      = "barcode_data/api_keys.json"
AUDIT_LOG_FILE     = "barcode_data/deletion_audit.log"

SHARD_LIMIT        = 10000               # rows per shard
MAX_IMAGE_SIZE     = 5 * 1024 * 1024     # 5 MiB
MAX_REDIRECTS      = 3                   # image redirect hops
MAX_BATCH_SIZE     = 100                 # bulk operations
MAX_DELETE_INDICES = 50                  # delete indices per call
DEFAULT_PER_PAGE   = 50                  # pagination
MAX_PER_PAGE       = 500                 # pagination cap
IMAGE_MODE         = 'redirect'          # or 'proxy'
```

Environment variables:

Variable Purpose
BARCODE_API_KEY Initial key (first startup only)
PORT Port for render.py
RENDER_EXTERNAL_URL Self-ping target

---

✦ Security Model

What the server protects

Layer Implementation
Authentication X-API-Key header on writes
Delete safety Confirm header + index-only + audit log + rate limit
URL validation Public IPv4/IPv6 only; blocks private, loopback, reserved, multicast, link-local, unspecified
Redirect safety Manual follow, max 3 hops, revalidate each hop
Content type Must be image/*
Size limit 5 MiB streaming cap
CSV injection Prefixes + - = @ with ' on add and update
Atomic writes JSON and CSV use temp file + os.replace
Race safety Thread locks on DB, metrics, and API key cache

What it does NOT protect

· ✕ Not a WAF — deploy behind nginx or Cloudflare
· ✕ Not encrypted — use HTTPS via reverse proxy
· ✕ Keys are stored plaintext — protect the file
· ✕ No user-level permissions — all-or-nothing per key

Recommended deployment

```
Internet → Cloudflare/nginx (TLS) → Gunicorn (2 workers) → This app
           ↑ rate limits, IP filtering, DDoS
```

---

◎ Metrics & Health

/api/health

```json
{
  "status": "ok",
  "uptime": "2h 15m 30s",
  "uptime_seconds": 8130,
  "shards": 2,
  "barcodes": 128,
  "active_shard": "my_products_1.csv"
}
```

/api/stats

```json
{
  "products": {
    "unique_barcodes": 128,
    "total_products": 356,
    "with_image": 312,
    "without_image": 44,
    "avg_per_barcode": 2.78
  },
  "storage": {
    "total_size_bytes": 251187,
    "index_size_bytes": 39116,
    "total_shards": 2,
    "shards": [
      {"name": "my_products_0.csv", "size_bytes": 203468}
    ]
  },
  "active_shard": {"name": "my_products_1.csv", "rows": 156, "limit": 10000},
  "api_keys": {"total": 3, "enabled": 3, "disabled": 0}
}
```

Prometheus scraping

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'barcode-server'
    metrics_path: '/api/metrics'
    static_configs:
      - targets: ['localhost:5000']
```

---

▸ Deployment

Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY barcode_server.py .
VOLUME ["/app/barcode_data"]
EXPOSE 5000
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "barcode_server:app"]
```

```bash
docker build -t barcode-server .
docker run -d -p 5000:5000 \
  -v $(pwd)/barcode_data:/app/barcode_data \
  -e BARCODE_API_KEY=my-secret \
  barcode-server
```

Nginx reverse proxy

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 30s;
    }
}
```

Systemd service

```ini
[Unit]
Description=Barcode Server
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/barcode-server
Environment="BARCODE_API_KEY=secret"
ExecStart=/opt/barcode-server/.venv/bin/gunicorn --workers 2 --bind 0.0.0.0:5000 barcode_server:app
Restart=always

[Install]
WantedBy=multi-user.target
```

---

▤ Backup & Recovery

Backup everything together:

```bash
tar -czf barcode-backup-$(date +%Y%m%d).tar.gz barcode_data/
```

Files that matter:

```
barcode_data/
├── index.json           ← CRITICAL (source of truth)
├── api_keys.json        ← CRITICAL
├── deletion_audit.log   ← IMPORTANT (audit trail)
└── my_products_*.csv    ← REBUILDABLE from index.json
```

Recovery:

1. Restore barcode_data/ from the backup
2. Restart the server — the index is loaded into memory
3. Shards are used only for export

---

✕ Error Codes

Status Meaning Common Cause
200 Success —
400 Bad request Invalid JSON, missing field, invalid index, empty batch, invalid image, missing confirm header
401 Unauthorized Missing or invalid API key
403 Forbidden API key disabled
404 Not found Barcode or image missing
429 Rate limited Too many requests — wait
500 Server error Image download failed, unexpected exception

Error Response Format

```json
{"error": "Human-readable message"}
```

---

▸ FAQ

<details>
<summary><b>Can I have multiple products under one barcode?</b></summary>

Yes. Duplicate detection is on barcode + name. Different names under the same barcode are allowed.

</details>

<details>
<summary><b>What happens when a shard reaches 10,000 rows?</b></summary>

A new shard (my_products_1.csv, my_products_2.csv, ...) is created automatically. Old shards stay untouched.

</details>

<details>
<summary><b>Why doesn't delete take a "delete all" option?</b></summary>

By design. A single API key leak or a UI bug shouldn't be able to wipe the database. Delete requires explicit indices plus a confirmation header.

</details>

<details>
<summary><b>Can I use this in a mobile app?</b></summary>

Yes. Point your image widget directly at /api/lookup/<barcode>/image. The 302 redirect is followed automatically by browsers, Glide, SDWebImage, Coil, Flutter, and React Native.

</details>

<details>
<summary><b>Why are lookup images redirects by default?</b></summary>

Because 302 keeps the server's bandwidth and RAM near zero, which is critical for concurrency. If a source blocks hotlinks, add ?proxy=1 to stream it.

</details>

<details>
<summary><b>How do I bulk import 1,000 products?</b></summary>

Use /api/add-batch in batches of 100. Ten requests total.

</details>

<details>
<summary><b>Is the API key secure?</b></summary>

It's sent as a header (not URL), so it's not logged in access logs. But keys are stored plaintext in api_keys.json — protect that file.

</details>

<details>
<summary><b>Can I run this with multiple workers?</b></summary>

Yes, but each worker has separate caches, metrics, and rate limits. For proper multi-worker use, add Redis for cache and limits plus a real database.

</details>

<details>
<summary><b>What happens if I delete all products under a barcode?</b></summary>

The barcode key is removed from the index entirely. The next lookup returns 404.

</details>

<details>
<summary><b>Where is the "delete all" endpoint?</b></summary>

There isn't one — intentionally. See Security Model.

</details>

---

▸ Troubleshooting

<details>
<summary><b>Image shows broken (403/404)</b></summary>

The source blocks hotlinking. Use ?proxy=1:

```
/api/lookup/12345/image?proxy=1
```

</details>

<details>
<summary><b>Delete returns 400</b></summary>

Checklist:

☐ X-API-Key header present and valid
☐ X-Confirm-Delete: YES-DELETE header present
☐ JSON body contains {"indices": [...]} with integers
☐ Indices are within range for that barcode

</details>

<details>
<summary><b>Port 5000 already in use</b></summary>

```bash
gunicorn --bind 0.0.0.0:8000 barcode_server:app
```

</details>

<details>
<summary><b>Data looks corrupted</b></summary>

1. Stop the server
2. Back up barcode_data/
3. Inspect index.json (source of truth)
4. If shards are broken, restore them from the index by triggering an update or delete

Never run multiple writer processes against the same barcode_data/.

</details>

<details>
<summary><b>Rate limit errors (429)</b></summary>

Wait for the window to reset. In multi-worker setups, limits differ per worker.

</details>

<details>
<summary><b>Search returns empty</b></summary>

Check that q is non-empty. It searches product name and barcode as case-insensitive substrings.

</details>

---

✦ Contributing

We welcome contributions.

1. Fork the repo
2. Create a branch — git checkout -b feature/amazing-thing
3. Make focused changes — one feature per PR
4. Update README if behavior changed
5. Test locally — API and CLI
6. Open a PR with a clear description

Before you push

Never commit these files:

```
barcode_data/api_keys.json
barcode_data/deletion_audit.log
barcode_data/*.csv
.env
*.log
```

Suggested .gitignore

```gitignore
barcode_data/
.venv/
__pycache__/
*.pyc
.env
*.log
```

---

▤ License

GPL-3.0-or-later

This project should include a matching LICENSE file in the repo root so the legal terms are explicit. Confirm with the maintainer before redistribution.

---

▸ Support

· Bug reports — Open an issue
· Feature requests — Open an issue with a [Feature] prefix
· Security issues — Do not open a public issue. Contact the maintainer privately.

Never post API keys, private data, or production exports in public issues.

---

<div align="center">

Built with care for the developer community

Star this repo if it helped you.

</div>
