# Secure Barcode API Server

A Python/Flask barcode API and command-line tool for storing product names and image URLs against barcodes. The application supports multiple products per barcode, API-key authentication, configurable lookup/image limits, sharded CSV storage, JSON indexing, image validation, background image caching, ZIP export, metrics, and interactive product management.

> **Security warning:** Never use real API keys in source control. If a key has been committed, revoke it and create a new one immediately.

## Contents

- [Features](#features)
- [Project structure](#project-structure)
- [Requirements and installation](#requirements-and-installation)
- [Running the server](#running-the-server)
- [First startup behavior](#first-startup-behavior)
- [CLI commands](#cli-commands)
- [Authentication and API keys](#authentication-and-api-keys)
- [REST API](#rest-api)
- [Rate limits](#rate-limits)
- [Storage model](#storage-model)
- [Caching and background image work](#caching-and-background-image-work)
- [Security behavior](#security-behavior)
- [Configuration](#configuration)
- [Metrics](#metrics)
- [Errors and status codes](#errors-and-status-codes)
- [Troubleshooting](#troubleshooting)
- [Production notes](#production-notes)
- [Contributing](#contributing)
- [License](#license)

## Features

- Public barcode lookup.
- Multiple products under the same barcode.
- Protected product creation, product updates, and ZIP export.
- Interactive CLI for adding, editing, listing, and inspecting products.
- CLI API-key creation, removal, and listing.
- Per-key lookup and image-download limits.
- CSV shards that rotate after 10,000 data rows.
- JSON index for fast in-memory lookup.
- One-hour lookup cache and 24-hour image cache.
- Background image prefetch after adding a product.
- Image URL validation and private-network checks.
- CSV formula/injection mitigation when adding products.
- Runtime metrics and compressed CSV export.

## Project structure

```text
.
├── barcode_server.py       # Flask app, storage layer, API routes, CLI commands
├── render.py               # Optional Render self-ping runner
├── requirements.txt        # Python dependencies
├── README.md               # Documentation
└── barcode_data/
    ├── api_keys.json       # API-key configuration
    ├── index.json          # Barcode-to-products index
    └── my_products_0.csv   # Product storage shard
```

`barcode_data/` is runtime data. Back up `index.json`, `api_keys.json`, and all `my_products_*.csv` files together.

## Requirements and installation

Python 3.8 or newer is recommended.

```bash
git clone https://github.com/NRXQuantum/barcode-server.git
cd barcode-server

python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

The dependencies are Flask, Flask-Limiter, Flask-Caching, Requests, and Gunicorn.

## Running the server

### Development server

```bash
python barcode_server.py
```

The application listens on `http://localhost:5000` and binds to `0.0.0.0`.

### Production WSGI server

```bash
gunicorn --workers 2 --bind 0.0.0.0:5000 barcode_server:app
```

The current cache, metrics, rate limiter, and local file storage are process-local. Multiple workers do not share their in-memory state and should not independently write the same data directory without an external coordination strategy.

### Render runner

```bash
python render.py
```

`render.py` starts the Flask development server and a daemon thread that requests `/api/` every 12 minutes. It uses `PORT` for the listening port and `RENDER_EXTERNAL_URL` for the ping target. This self-ping is optional and should not be treated as a replacement for health checks or production WSGI configuration.

## First startup behavior

When the application starts:

1. `barcode_data/` is created if necessary.
2. If `barcode_data/api_keys.json` does not exist, an initial key is created from `BARCODE_API_KEY`; otherwise the code's fallback value is used.
3. `barcode_data/index.json` is loaded if present.
4. If no shard exists, `my_products_0.csv` is created.
5. A legacy root-level `my_products.csv` may be migrated when no index exists.
6. An older single-product index format is converted to the current list-per-barcode format.

Set the initial key before the first run:

```bash
# Linux/macOS
export BARCODE_API_KEY="replace-with-a-long-random-secret"

# Windows PowerShell
# $env:BARCODE_API_KEY = "replace-with-a-long-random-secret"
```

`BARCODE_API_KEY` is only used to create the initial file. It does not replace keys already stored in `barcode_data/api_keys.json`.

## CLI commands

Run commands from the repository root. The program does not currently provide an argparse-based `--help` command; the supported commands are listed below.

### Add products interactively: `--add`

```bash
python barcode_server.py --add
```

The program asks for:

```text
Barcode:
Product Name:
Image URL (optional):
Add another? (y/n):
```

Behavior:

- Empty barcode and empty product name are rejected.
- The image URL is optional.
- Multiple products may use the same barcode.
- The same barcode and product name cannot be added twice.
- A supplied image URL is validated before it is stored.
- Image caching is submitted to the background executor after a successful add.
- Type `y` to continue adding products; any other answer ends the loop.

### Edit a product interactively: `--edit`

```bash
python barcode_server.py --edit
```

Behavior:

- Enter a barcode first.
- If there are multiple products, select a zero-based index such as `0` or `1`.
- Press Enter for the new name to keep the existing name.
- Press Enter for the new image URL to keep the existing image.
- Leaving both fields empty cancels the update.
- A changed image is validated before saving.
- The update rewrites all CSV shards from the current JSON index.
- The barcode lookup cache is cleared after a successful update.

### List all products: `--list`

```bash
python barcode_server.py --list
```

Prints a terminal table containing the barcode, product name, and image URL. Long product names are shortened for display. This command shows the total number of product records, not only unique barcodes.

### Show storage statistics: `--stats`

```bash
python barcode_server.py --stats
```

Displays:

- Unique barcodes.
- Total products, including multiple products under one barcode.
- Number of CSV shards.
- Active shard name and row count.

### Add an API key: `--add-key`

```bash
python barcode_server.py \
  --add-key "APP_KEY" \
  --name "Android App" \
  --limits "lookup:500,image:20,add:10"
```

Required arguments:

- `--add-key <key>`
- `--name <name>`

Optional argument:

- `--limits lookup:number,image:number,add:number`

Example with default limits:

```bash
python barcode_server.py --add-key "APP_KEY" --name "Internal Tool"
```

If the key already exists, the command returns `Key already exists.`. Invalid limit syntax is ignored with a warning. The configured `lookup` and `image` values are used by the dynamic lookup/image limit functions. The current `/api/add` and `/api/update/<barcode>` routes still use a fixed `5 per second` route limit; the stored `add` value is not currently used by those decorators.

Do not use an artificially large or “unlimited” key in a public or untrusted environment.

### Remove an API key: `--remove-key`

```bash
python barcode_server.py --remove-key "APP_KEY"
```

Removes the key from `barcode_data/api_keys.json`. If it does not exist, the command returns `Key not found.`.

### List API keys: `--list-keys`

```bash
python barcode_server.py --list-keys
```

Displays each key in masked form, its name, enabled status, and configured limits. The command does not provide a command to enable or disable a key; that currently requires editing the JSON configuration carefully or adding such functionality to the code.

### Unsupported or unknown commands

```bash
python barcode_server.py --unknown
```

The program prints the supported command names. There is no built-in `--help` parser at present.

## Authentication and API keys

Protected endpoints require the `X-API-Key` header:

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  http://localhost:5000/api/export
```

Each key record has this shape:

```json
{
  "name": "Application name",
  "enabled": true,
  "limits": {
    "lookup": 200,
    "image": 5,
    "add": 5
  }
}
```

- Missing key: `401` with `Missing X-API-Key header.`
- Unknown key: `401` with `Invalid API Key.`
- Disabled key: `403` with `API Key is disabled.`
- Keys are stored as plaintext JSON by the current implementation.
- Key changes are loaded from the file during requests, but the file is not encrypted or atomically updated.

## REST API

Base URL:

```text
http://localhost:5000/api
```

### Endpoint summary

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/` | No | API information and endpoint list |
| `GET` | `/api/lookup/<barcode>` | No | Return all products for a barcode |
| `GET` | `/api/lookup/<barcode>/image` | No | Download the first product image |
| `POST` | `/api/add` | Yes | Add a product |
| `PUT` | `/api/update/<barcode>` | Yes | Update one product by index |
| `GET` | `/api/all` | No | Return all products |
| `GET` | `/api/export` | Yes | Download all CSV shards as a ZIP |
| `GET` | `/api/metrics` | No | Return process-local metrics |

### `GET /api/`

```bash
curl http://localhost:5000/api/
```

Returns the API description and endpoint list.

### `GET /api/lookup/<barcode>`

```bash
curl http://localhost:5000/api/lookup/6281006451865
```

Response:

```json
{
  "barcode": "6281006451865",
  "products": [
    {
      "name": "Example Product",
      "image": "https://example.com/product.jpg",
      "shard": "my_products_0.csv"
    }
  ]
}
```

`products` is always a list when the barcode exists. If it does not exist:

```json
{"error":"Barcode not found."}
```

### `GET /api/lookup/<barcode>/image`

```bash
curl -OJ http://localhost:5000/api/lookup/6281006451865/image
```

If a barcode has multiple products, this endpoint downloads only the image of the first product (`products[0]`). It returns `404` when the barcode or image is missing.

### `POST /api/add`

Requires an API key and JSON body. `barcode` and `name` are required; `image` is optional.

```bash
curl -X POST http://localhost:5000/api/add \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "barcode": "6281006451865",
    "name": "Example Product",
    "image": "https://example.com/product.jpg"
  }'
```

Successful response:

```json
{
  "status": "ok",
  "message": "Product added successfully. Image caching in background.",
  "shard": "my_products_0.csv"
}
```

The request may contain text around a URL; the current implementation extracts the first HTTP/HTTPS URL it finds. Duplicate barcode/name combinations and invalid image URLs return `400`.

### `PUT /api/update/<barcode>`

Requires an API key. `index` is required and is zero-based within the barcode's `products` list.

```bash
curl -X PUT http://localhost:5000/api/update/6281006451865 \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "index": 0,
    "name": "Updated Product Name",
    "image": "https://example.com/updated.jpg"
  }'
```

Only `name`, only `image`, or both may be changed. Omitting a field keeps its previous value. An invalid index, missing index, invalid image, or no actual change returns `400`.

Successful response:

```json
{
  "status": "ok",
  "message": "Product updated successfully.",
  "updated_product": {
    "name": "Updated Product Name",
    "image": "https://example.com/updated.jpg",
    "shard": "my_products_0.csv"
  }
}
```

### `GET /api/all`

```bash
curl http://localhost:5000/api/all
```

Returns a flattened list. Each item contains `barcode`, `product_name`, `image_url`, and `shard`.

### `GET /api/export`

Requires an API key:

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  http://localhost:5000/api/export \
  --output all_shards.zip
```

The ZIP contains the current `my_products_*.csv` files.

### `GET /api/metrics`

```bash
curl http://localhost:5000/api/metrics
```

Example response:

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

`total_entries` is the number of unique barcode keys, not the number of product rows. Metrics reset when the process restarts and are not shared between workers.

### Compatibility redirects

The application also exposes `/`, `/lookup/<barcode>`, `/lookup/<barcode>/image`, `/add`, `/all`, and `/export`. Prefer the `/api/...` paths for new clients. The `/add` and `/export` compatibility routes call the protected handlers and therefore still require the appropriate API key.

## Rate limits

The current route configuration is:

| Operation | Limit |
|---|---|
| API home | `30 per second` |
| Lookup without key | `20 per second` |
| Lookup with key | The key's `lookup` value per second; fallback `200 per second` if absent |
| Image without key | `1 per 3 seconds` |
| Image with key | The key's `image` value per second; fallback `5 per second` if absent |
| Add | `5 per second` |
| Update | `5 per second` |
| All products | `30 per second` |
| Export | `2 per minute` |
| Metrics | `10 per minute` |
| Global defaults | `200 per day` and `50 per hour` where applicable |

The limiter uses `memory://`, so state is process-local and resets after restart. In a multi-worker deployment, workers do not share the limiter state.

## Storage model

### JSON index

`barcode_data/index.json` maps each barcode to a list:

```json
{
  "1234567890123": [
    {
      "name": "Product name",
      "image": "https://example.com/image.jpg",
      "shard": "my_products_0.csv"
    }
  ]
}
```

### CSV shards

Each shard contains:

```text
barcode,product_name,image_url
```

The active shard rotates after 10,000 data rows. New products are appended to the active shard and the JSON index is rewritten. The index is loaded into memory at startup for lookups.

### Multiple products and duplicate rule

- A barcode may have multiple product records.
- A duplicate is defined as the same barcode and the same product name.
- The image URL is not used in the duplicate comparison.
- Updating a product rewrites all shards from the current index.
- Do not manually edit the JSON or CSV files while the server is running.

### Legacy data

If a root-level `my_products.csv` exists and the index does not, startup attempts to migrate it to `barcode_data/my_products_0.csv`. An old index containing one object per barcode is converted to a list-per-barcode format.

## Caching and background image work

- Lookup responses are cached for 3,600 seconds.
- Images are cached for 86,400 seconds under keys such as `img_<barcode>`.
- Product creation submits image downloading to a five-worker `ThreadPoolExecutor`.
- Product lookup cache is deleted after a successful update.
- The current update path does not explicitly delete the old image cache entry; an image change may therefore continue returning cached content until that cache entry expires.
- Cache contents are lost on restart and are not shared between processes.

## Security behavior

The application currently implements:

- HTTP/HTTPS-only image URLs.
- Hostname resolution before image access.
- Rejection of private, loopback, multicast, and link-local IPv4 addresses.
- Explicit blocking of `169.254.*` link-local addresses.
- `image/*` content-type validation.
- A 5 MiB streaming download limit.
- No redirect following during validation or download.
- Prefixing values beginning with `+`, `-`, `=`, or `@` when adding CSV rows.
- API-key checks for protected endpoints.
- Request rate limiting.

These are not a complete security boundary. The current implementation should also be deployed behind TLS, network egress controls, restricted file permissions, and proper secret management. The URL check skips IPv6 addresses rather than applying the same private-address checks. Also, the update path should be reviewed because its rewritten CSV values do not apply the same sanitization path used by `add()`.

## Configuration

The main constants are in `barcode_server.py`:

| Setting | Default | Meaning |
|---|---:|---|
| `DATA_DIR` | `barcode_data` | Runtime data directory |
| `INDEX_FILE` | `barcode_data/index.json` | JSON index path |
| `API_KEYS_FILE` | `barcode_data/api_keys.json` | API-key file |
| `SHARD_LIMIT` | `10000` | Data rows per shard |
| `MAX_IMAGE_SIZE` | `5 * 1024 * 1024` | Maximum image size |
| Lookup cache | `3600` seconds | Lookup cache lifetime |
| Image cache | `86400` seconds | Image cache lifetime |
| `BARCODE_API_KEY` | unset | Initial key source |
| `PORT` | `5000` | Port used by `render.py` |
| `RENDER_EXTERNAL_URL` | Code fallback URL | `render.py` ping target |
| `PING_INTERVAL` | `720` seconds | `render.py` ping interval |

Most settings are source constants, not environment variables. Changing them requires editing the source and restarting the application.

## Metrics

The metrics endpoint reports:

- `total_requests`
- `cache_hits`
- `cache_misses`
- `cache_hit_ratio`
- `avg_response_time_ms`
- `active_shard`
- `total_entries`

The average response time is calculated from the most recent 1,000 recorded request times. Metrics are in-memory and process-local. They are not durable monitoring data.

## Errors and status codes

| Status | Meaning |
|---:|---|
| `200` | Request succeeded |
| `400` | Invalid JSON, missing field, invalid index, duplicate, or invalid image |
| `401` | Missing or invalid API key |
| `403` | API key is disabled |
| `404` | Barcode or image not found |
| `429` | Rate limit exceeded |
| `500` | Image download or unexpected server error |

Typical error responses:

```json
{"error":"Missing X-API-Key header."}
```

```json
{"error":"Invalid API Key."}
```

```json
{"error":"Barcode and Name are required fields."}
```

```json
{"error":"No image associated with this product."}
```

## Troubleshooting

### Port already in use

```bash
gunicorn --bind 0.0.0.0:8000 barcode_server:app
```

### Image validation fails

Confirm that the URL is reachable, uses HTTP/HTTPS, resolves to a public IPv4 address, returns `Content-Type: image/*`, and is no larger than 5 MiB.

### Product is not found

Confirm the barcode value after trimming whitespace. Use `python barcode_server.py --list` or inspect the index.

### Data files look inconsistent

Stop the server, back up `barcode_data/`, and inspect the JSON index and shards together. Do not run multiple writer processes against the same local files.

### `429 Too Many Requests`

Wait for the applicable window to reset. Remember that rate-limit state is in memory and may differ between workers.

## Production notes

- Use HTTPS and a reverse proxy or managed ingress.
- Rotate every key that has been exposed or committed.
- Do not publish `api_keys.json` or production CSV data.
- Back up the JSON index and every shard together.
- The in-process lock protects threads in one process only; it does not coordinate Gunicorn workers or multiple instances.
- JSON and CSV writes are not a single atomic transaction.
- Updating a product rewrites all shards and can be expensive for large datasets.
- For high concurrency or large data, use a database and shared cache/rate-limit backend.
- Add automated tests before changing storage or security behavior.
- Pin dependency versions and update them regularly after testing.

## Contributing

1. Create a feature branch.
2. Make a focused change.
3. Update README examples when behavior changes.
4. Test the affected CLI or API behavior locally.
5. Open a pull request.

Never include real API keys, private data, or production exports in commits.

## License

The project documentation identifies this project as `GPL-3.0-or-later`. A matching `LICENSE` file should be added to the repository so the legal terms are explicit. Confirm the license with the maintainer before redistribution.

## Support

For bugs and feature requests, open a GitHub issue. Do not publish API keys, private product data, or sensitive security details in public issues.
