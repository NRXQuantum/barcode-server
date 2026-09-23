
<div align="center">

# ◆ Barcode Server

**A production-grade REST API & CLI for storing products, barcodes, and images.**

Fast · Secure · Self-hosted · Zero-config

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-2.x-black)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)](LICENSE)
[![Status](https://img.shields.io/badge/status-stable-brightgreen)]()
[![PRs](https://img.shields.io/badge/PRs-welcome-blueviolet)]()

[▸ Quick Start](#-quick-start) &nbsp;·&nbsp; [▸ Features](#-features) &nbsp;·&nbsp; [▸ API Reference](#-api-reference) &nbsp;·&nbsp; [▸ CLI Reference](#-cli-reference) &nbsp;·&nbsp; [▸ FAQ](#-faq)

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

**Try the live demo:**

```

https://barcode-server-6vss.onrender.com

```

> The demo runs on a free Render instance. It may take 10–30 seconds to wake up after inactivity. Data on the demo is public and may be cleared periodically — do not store private information there.

**Run your own in 60 seconds:**

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

Test it (local or live):

```bash
BASE="https://barcode-server-6vss.onrender.com"

# Add a product
curl -X POST $BASE/api/add \
  -H "X-API-Key: my-super-secret-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"barcode":"1234567890","name":"Coca Cola 500ml","image":"https://example.com/coke.jpg"}'

# Look it up (no auth required)
curl $BASE/api/lookup/1234567890

# Health check
curl $BASE/api/health
```

Common base URLs:

Environment Base URL
Local development http://localhost:5000
Live demo (Render) https://barcode-server-6vss.onrender.com
Your own deployment https://your-domain.com

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
· Design Limits & Non-Goals

Using the Server

· CLI Reference
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
▣ Bulk Operations Add/lookup up to 100 items per call
▸ Bulk Edit CLI Edit many products from CSV or interactively
■ Safe Delete Index-based, audit-logged, confirm header
◎ Health & Stats JSON endpoints for monitoring
✦ CSV Injection Guard Strips control chars + formula prefix guard
✦ IPv4 + IPv6 Safe Rejects private/reserved addresses
▤ Atomic Writes JSON & CSV use temp file + os.replace
◎ Index Auto-Rebuild Rebuilds index.json from CSV shards if lost
▤ Multi-Worker Aware Detects external index.json changes via mtime

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

1. Add — Validate image URL → Append to active CSV shard → Update JSON index (atomic) → Clear lookup cache → Background image prefetch
2. Lookup — Check cache → Fall back to in-memory index → Return list of products
3. Image — Return 302 to original URL (fast) or stream via proxy (fallback)
4. Delete — Verify API key + confirm header → Remove indices → Rewrite shards → Log to audit
5. Recovery — If index.json is missing or corrupted, rebuild it from CSV shards automatically on startup

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
flask-caching File-based cache
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

Warning — multi-worker setups: Each worker keeps its own rate limiter and metrics. The app automatically picks up external changes to index.json (via mtime check), so writes propagate across workers. The cache is shared on the same machine via FileSystemCache. For high-concurrency or multi-machine deployments, use Redis for cache and rate limits, and a proper database.

Render.com (self-pinging)

```bash
python render.py
```

Pings /api/ every 12 minutes to keep the free instance alive. Uses RENDER_EXTERNAL_URL if set.

Live demo

```
https://barcode-server-6vss.onrender.com
```

Free Render instances sleep after inactivity. First request may take 10–30 seconds.

---

▤ Storage Model

Directory Layout

```
barcode_data/
├── index.json              # barcode → [products]  (source of truth, auto-rebuildable)
├── api_keys.json           # API key registry       (backup required)
├── deletion_audit.log      # every delete (success + failure)
├── cache/                  # FileSystemCache files
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
Auto-recovery Index rebuilt from shards if missing/corrupted

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
· ▸ Effectively unlimited concurrency
· ▸ Blocked by hotlink-protected sites
· ▸ Depends on the external host being online

■ Mode B — Proxy (fallback)

```
Client → API: "Give me image for 12345 (?proxy=1)"
API    → source.com: "Give me the image"
source.com → API: [image bytes]
API    → Client: [image bytes]
```

· ▸ Works everywhere, including hotlink-protected sites
· ▸ Uses server bandwidth + RAM
· ▸ Cached for 24 hours per barcode

Use proxy when:

· The source blocks hotlinking (Amazon, Flipkart)
· The URL requires authentication headers
· You need to hide the source URL
· The external host is unreliable

Switch mode:

```bash
# Per-request
curl "http://localhost:5000/api/lookup/12345/image?proxy=1"

# Global default (edit source)
IMAGE_MODE = 'proxy'
```

---

▤ First Startup Behavior

When the application starts:

1. barcode_data/ and barcode_data/cache/ are created if necessary.
2. If api_keys.json does not exist, an initial key is created from BARCODE_API_KEY (or a fallback).
3. index.json is loaded if present.
4. If index.json is missing or corrupted, it is rebuilt automatically from CSV shards.
5. A legacy root-level my_products.csv may be migrated to barcode_data/my_products_0.csv.
6. An older single-product index format is converted to the current list-per-barcode format.
7. If no shard exists, my_products_0.csv is created.

---

✦ Design Limits & Non-Goals

This server is deliberately simple. It is not a replacement for a database.

Scale

What Comfortable limit
Unique barcodes ~100,000 in memory
Total rows CSV shards grow linearly; no secondary indexes
Concurrent writes Single writer — one process should own the data dir
Concurrent reads Effectively unlimited for lookup (in-memory)

Beyond these, use PostgreSQL, SQLite with WAL, or a similar database.

Multi-Worker Gotchas

Running gunicorn --workers 4 creates four independent servers that happen to share a directory. Each has its own:

· In-memory index (auto-reloaded when index.json mtime changes)
· Lookup cache (FileSystemCache — shared on the same machine)
· Rate-limit counters (in-memory, per worker)
· Metrics (in-memory, per worker)

Symptoms to expect:

· Rate limits are multiplied by the number of workers
· Metrics from /api/metrics show only the worker that answered
· Writes are visible across workers after a short moment (mtime reload)

Fix for true multi-worker: use Redis for cache and rate limits, and a real database.

Public Lookup is Intentional

GET /api/lookup/<bc> and /api/search have no authentication. This is by design — the API is intended for public product lookup, the same way a public catalog works.

If your data is private, put the whole server behind:

· A reverse proxy with basic auth, or
· Cloudflare Access, or
· VPN / IP allowlist

There is no per-barcode access control built in.

API Key Storage

Keys are stored plaintext in barcode_data/api_keys.json.

Minimum hardening:

```bash
chmod 600 barcode_data/api_keys.json
chown www-data:www-data barcode_data/api_keys.json
```

For production, mount this file from a secret manager (Docker secret, Kubernetes Secret, Vault, etc.).

Redirect Mode Depends on the External Host

The default image mode returns a 302 to the source URL. This means:

· If the source host is down → image is broken
· If the source deletes the file → image is gone
· If the source blocks hotlinks → image is blocked

The server is not a CDN. It is a lookup service that points to images. Use ?proxy=1 if you need the server to own the image bytes, and accept the bandwidth cost.

CSV Injection Guard — Scope

The guard strips ASCII control characters and newlines, collapses spaces, and prefixes + - = @ with ' on add and update. This blocks the common spreadsheet-formula vector. It does not attempt to sanitize:

· Unicode bidirectional or zero-width characters
· Delimiter confusion beyond standard CSV escaping

Treat CSV output as untrusted data, not as a hardened format.

No "Delete All"

There is intentionally no endpoint to delete the whole database. A single leaked API key or a UI bug should not be able to wipe everything. Deleting the entire barcode_data/ directory requires manual filesystem action.

---

▸ CLI Reference

All commands run from the repo root.

Command summary

Command Purpose
--add Add one product interactively
--add-multi Add many (interactive or from CSV)
--add-multi --yes Add many, auto-accept conflicts
--edit Edit one product interactively
--edit-multi Edit many (interactive or from CSV)
--list List all products
--stats Show dashboard statistics
--add-key Register a new API key
--remove-key Remove an API key
--list-keys List registered API keys

---

▸ --add — Add one product

```bash
python barcode_server.py --add
```

Prompts:

```
Barcode:
Product Name:
Image URL (optional):
Add another? (y/n):
```

· Empty barcode / name → rejected
· Image URL is validated before storing
· Press y to add another, any other key to stop

---

▣ --add-multi — Add many products

```bash
python barcode_server.py --add-multi
```

Two modes:

Mode 1 — Interactive

```
Mode [1/2] (default 1): 1
How many products? 3

▸ [1/3]
  Barcode : 111
  Name    : Product A
  Image   : https://a.jpg
  ✓ Added · 111 → Product A
```

Mode 2 — From CSV file

```
Mode [1/2] (default 1): 2
CSV file path: products.csv
```

CSV format (barcode,product_name,image_url — same as shards):

```csv
barcode,product_name,image_url
111,Product A,https://a.jpg
222,Product B,
333,Product C,https://c.jpg
```

Conflict handling:

Situation Default With --yes
New barcode ✅ Add ✅ Add
barcode + name + image identical ⏭ Skip ⏭ Skip
barcode + name same, image different ❓ Ask at end ✅ Add
barcode same, name different ✅ Add ✅ Add
Different barcode ✅ Add ✅ Add

Auto-accept conflicts:

```bash
python barcode_server.py --add-multi --yes
```

---

▸ --edit — Edit one product

```bash
python barcode_server.py --edit
```

Prompts:

```
Enter barcode to edit:
```

· If the barcode has multiple products, shows a list and asks for the index
· Press Enter for the new name/image to keep the current value
· Leaving both empty cancels the edit

---

▸ --edit-multi — Edit many products

```bash
python barcode_server.py --edit-multi
```

Two modes:

Mode 1 — Interactive

```
Mode [1/2] (default 1): 1
How many edits? 2

▸ [1/2]
  Barcode : 6281006451865
  Found   : Paracetamol 500mg  · https://a.jpg
  New name   (Enter = keep): Paracetamol Extra
  New image  (Enter = keep): 
  ✓ Updated · 6281006451865
```

Multiple products under one barcode:

```
  Barcode : 6281006451865
  Available products:
    [0] Paracetamol 500mg  · https://a.jpg
    [1] Napa 650mg  · https://b.jpg
  Which product? (name): Napa 650mg
  Current : Napa 650mg  · https://b.jpg
  New name   (Enter = keep): Napa Extra
  New image  (Enter = keep): 
  ✓ Updated · 6281006451865 · Napa 650mg
```

Mode 2 — From CSV file

CSV format (barcode,product_name,new_name,new_image):

```csv
barcode,product_name,new_name,new_image
6281006451865,,Updated Paracetamol,https://new.jpg
6281006451866,Napa 650mg,Napa Extra,
6281006451867,Paracetamol 500mg,,https://new-c.jpg
```

Column Required? If blank
barcode ✅ Row skipped
product_name ❌ Uses the only product (if barcode has 1)
new_name ❌ Keeps old name
new_image ❌ Keeps old image

Identifier rules:

· barcode-এ ১টা প্রোডাক্ট → শুধু barcode দিলেই হবে
· barcode-এ একাধিক প্রোডাক্ট → name দিতে হবে (নাহলে "multiple products, name required")

---

▤ --list — List all products

```bash
python barcode_server.py --list
```

Prints a table: barcode | name | image URL.

---

◎ --stats — Dashboard

```bash
python barcode_server.py --stats
```

Displays a colored dashboard:

```
▁▂▃▄▅▆▇█████████████████████████████████████████████████████▇▆▅▄▃▂▁
                 ❰  ◆  BARCODE SERVER STATISTICS  ❱
▁▂▃▄▅▆▇█████████████████████████████████████████████████████▇▆▅▄▃▂▁

────────────────────  ▣  PRODUCTS  ────────────────────
    Unique Barcodes        : 128
    Total Products         : 356
    ...

────────────────────  ◈  IMAGES  ────────────────────
    With Image URL         : 312  (87.6%)
    ...

────────────────────  ▤  STORAGE  ────────────────────
    ...

────────────────────  ◎  ACTIVE SHARD  ────────────────────
    ...

────────────────────  ✦  API KEYS  ────────────────────
    ...
```

The same data is available as JSON via GET /api/stats.

---

✦ Key management

```bash
# Add a key with custom limits
python barcode_server.py --add-key "APP_KEY" \
  --name "Android App" \
  --limits "lookup:500,image:20,add:10"

# Remove
python barcode_server.py --remove-key "OLD_KEY"

# List
python barcode_server.py --list-keys
```

---

▸ API Reference

Base URL (local): http://localhost:5000/api
Base URL (live demo): https://barcode-server-6vss.onrender.com/api

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

▣ POST /api/add-batch

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

■ DELETE /api/delete/&lt;barcode&gt;

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

▤ GET /api/all

Flat response (backward compatible when no pagination params are supplied):

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

▣ POST /api/lookup-batch

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

◎ GET /api/health

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

◎ GET /api/stats

Public. JSON version of the --stats CLI dashboard.

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

◎ GET /api/metrics

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

✦ GET /api/export

Requires X-API-Key. Downloads all CSV shards as a ZIP.

```bash
curl -H "X-API-Key: YOUR_KEY" \
  http://localhost:5000/api/export -o all_shards.zip
```

---

◎ Common Workflows

Workflow 1 — Mobile App Integration

```
1. App scans barcode      →  GET /api/lookup/6281006451865
2. API returns product list
3. App displays           →  <img src="https://your-api/api/lookup/6281006451865/image">
4. Server returns 302     →  app auto-follows → image loads
```

No SDK needed. Works with <img> tags, Glide, SDWebImage, Flutter Image.network, and React Native.

Workflow 2 — Bulk Import from CSV

```bash
# Create products.csv with barcode,product_name,image_url
python barcode_server.py --add-multi
#   → mode 2
#   → products.csv
```

Workflow 3 — Bulk Edit from CSV

```bash
# Create edits.csv with barcode,product_name,new_name,new_image
python barcode_server.py --edit-multi
#   → mode 2
#   → edits.csv
```

Workflow 4 — Removing a Bad Entry

```bash
# 1. Check what's there
curl http://localhost:5000/api/lookup/12345

# 2. Delete index 1
curl -X DELETE http://localhost:5000/api/delete/12345 \
  -H "X-API-Key: ADMIN_KEY" \
  -H "X-Confirm-Delete: YES-DELETE" \
  -H "Content-Type: application/json" \
  -d '{"indices":[1]}'

# 3. Check the audit log
tail barcode_data/deletion_audit.log
```

Workflow 5 — Disaster Recovery

If index.json is deleted or corrupted, no action is needed — the server rebuilds it on next startup:

```bash
rm barcode_data/index.json
python barcode_server.py --stats
# → logs "index.json missing — rebuilding from CSV shards"
# → all products recovered
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
CACHE_DIR          = "barcode_data/cache"

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
CSV injection Strips control chars + newlines; prefixes + - = @ on add and update
Atomic writes JSON and CSV use temp file + os.replace
Race safety Thread locks on DB, metrics, and API key cache
Auto-recovery Index rebuilt from shards if lost

What it does NOT protect

· ✕ Not a WAF — deploy behind nginx or Cloudflare
· ✕ Not encrypted — use HTTPS via reverse proxy
· ✕ Keys are stored plaintext — protect the file with chmod 600
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

Full statistics snapshot — products, storage, active shard, API keys.

Prometheus scraping

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'barcode-server'
    metrics_path: '/api/metrics'
    static_configs:
      - targets: ['localhost:5000']
```

In multi-worker setups, Prometheus should scrape each worker separately or a Redis-backed exporter should be used to aggregate.

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

Render.com

The repo includes render.py which starts the Flask server and a background thread that pings /api/ every 12 minutes. Set RENDER_EXTERNAL_URL in the Render dashboard to your public URL.

---

▤ Backup & Recovery

Backup everything together:

```bash
tar -czf barcode-backup-$(date +%Y%m%d).tar.gz barcode_data/
```

Files that matter:

```
barcode_data/
├── index.json           ← CRITICAL (auto-rebuildable from shards)
├── api_keys.json        ← CRITICAL (NOT auto-rebuildable)
├── deletion_audit.log   ← IMPORTANT (audit trail)
├── cache/               ← DISPOSABLE
└── my_products_*.csv    ← REBUILDABLE, but needed to rebuild index
```

Recovery:

1. Restore barcode_data/ from backup
2. Restart the server — index is loaded into memory
3. If index.json is missing or corrupted, it is auto-rebuilt from CSV shards

The safest strategy is to back up the whole barcode_data/ folder. Losing api_keys.json means every client must be reconfigured.

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
<summary><b>What happens if index.json is deleted?</b></summary>

Nothing to worry about. On next startup, the server rebuilds index.json from the CSV shards. All products are recovered. Only reason to keep it is speed of startup on very large datasets.

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

Use --add-multi with a CSV file (mode 2). The CSV uses the same format as shards: barcode,product_name,image_url.

</details>

<details>
<summary><b>How do I bulk edit many products?</b></summary>

Use --edit-multi with a CSV file. Format: barcode,product_name,new_name,new_image. Leave product_name blank if the barcode has only one product.

</details>

<details>
<summary><b>Why does --edit-multi sometimes ask for product name?</b></summary>

If a barcode has only one product, barcode alone is enough. If it has multiple, name is required to identify which one to update. This is by design — otherwise the server wouldn't know which product to change.

</details>

<details>
<summary><b>Is the API key secure?</b></summary>

It's sent as a header (not URL), so it's not logged in access logs. But keys are stored plaintext in api_keys.json — protect that file with chmod 600.

</details>

<details>
<summary><b>Can I run this with multiple workers?</b></summary>

Yes, but each worker has separate rate limits and metrics. The index.json file is watched via mtime and reloaded automatically, so writes propagate. The cache is shared on the same machine via FileSystemCache. For proper multi-worker deployment, add Redis for rate limits and a real database.

</details>

<details>
<summary><b>What happens if I delete all products under a barcode?</b></summary>

The barcode key is removed from the index entirely. The next lookup returns 404.

</details>

<details>
<summary><b>How big can the dataset get?</b></summary>

Comfortable up to ~100,000 unique barcodes with ~200 MB index.json. Beyond that, use a real database. See Design Limits.

</details>

<details>
<summary><b>Does add() clear the lookup cache?</b></summary>

Yes. When a product is added under an existing barcode, the barcode's lookup cache is cleared so the next lookup sees the new product immediately.

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
<summary><b>--edit-multi fails with "multiple products, name required"</b></summary>

The barcode you're editing has more than one product. Add the product_name column in your CSV (or provide the name in interactive mode) to identify which product to update.

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
3. Delete index.json — the server rebuilds it from CSV shards on next start
4. If shards are also corrupted, restore from backup

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

<details>
<summary><b>Render demo is slow to respond</b></summary>

Free Render instances sleep after inactivity. The first request may take 10–30 seconds. render.py pings /api/ every 12 minutes to keep it warm.

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
barcode_data/index.json
barcode_data/cache/
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
