# Secure Barcode API Server

A Flask-based REST API and CLI for managing product barcodes, product names, and image URLs. The server supports multiple products per barcode, API-key authentication, per-key rate limits, sharded CSV storage, in-memory caching, background image prefetching, ZIP export, and runtime metrics.

> **Security notice:** Never commit real API keys to Git. If a key has ever been committed, revoke it and create a replacement immediately. Store production secrets in environment variables or a secret manager.

## Table of contents

- [Features](#features)
- [Technology](#technology)
- [Repository structure](#repository-structure)
- [Installation](#installation)
- [Running the server](#running-the-server)
- [Authentication](#authentication)
- [CLI reference](#cli-reference)
- [API reference](#api-reference)
- [Data storage](#data-storage)
- [Caching and background work](#caching-and-background-work)
- [Security behavior](#security-behavior)
- [Configuration](#configuration)
- [Monitoring](#monitoring)
- [Status codes and errors](#status-codes-and-errors)
- [Troubleshooting](#troubleshooting)
- [Production notes](#production-notes)
- [Contributing](#contributing)
- [License](#license)

## Features

- Barcode lookup with support for multiple products under one barcode.
- Product creation and update through a protected API and interactive CLI.
- API-key authentication using the `X-API-Key` request header.
- Per-key limits for lookup, image download, and product creation/update operations.
- Public lookup, image download, product listing, and metrics endpoints.
- CSV storage split into shards after 10,000 product rows.
- JSON index for fast lookups.
- One-hour product lookup cache and 24-hour image cache.
- Background image prefetch after a product is added.
- Image URL validation and private-network protection.
- CSV injection mitigation for values written to CSV files.
- ZIP export of all CSV shards.
- CLI key management and database statistics.

## Technology

- Python 3.8+
- Flask
- Flask-Limiter
- Flask-Caching
- Requests
- Gunicorn for WSGI deployment

## Repository structure

```text
.
├── barcode_server.py              # Flask app, storage layer, API routes, and CLI
├── render.py                      # Optional Render self-ping runner
├── requirements.txt               # Python dependencies
├── README.md                      # Project documentation
└── barcode_data/
    ├── api_keys.json              # API-key configuration
    ├── index.json                 # Barcode-to-product index
    └── my_products_0.csv          # Product data shard
```

`barcode_data/` is runtime data. Back it up carefully and do not expose `api_keys.json` publicly.

## Installation

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

The application creates `barcode_data/` and its initial files when they are missing. For a new deployment, set a strong key before the first start:

```bash
export BARCODE_API_KEY="replace-with-a-long-random-secret"
```

On Windows PowerShell:

```powershell
$env:BARCODE_API_KEY = "replace-with-a-long-random-secret"
```

## Running the server

### Development server

```bash
python barcode_server.py
```

The development server listens on `http://localhost:5000` and binds to `0.0.0.0`.

### Production with Gunicorn

```bash
gunicorn --workers 2 --bind 0.0.0.0:5000 barcode_server:app
```

Choose the worker count according to the deployment environment. The cache, metrics, and rate limiter use in-process memory, so multiple workers do not share those values.

### Render-style execution

`render.py` starts the Flask app and launches a background thread that pings `/api/` periodically. It reads the port from `PORT` and the target URL from `RENDER_EXTERNAL_URL`.

```bash
python render.py
```

In a managed production environment, prefer the platform's normal health checks and a production WSGI server where possible. A self-ping does not replace monitoring or proper deployment configuration.

## Authentication

Protected endpoints require an API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  http://localhost:5000/api/export
```

The key configuration contains:

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

- `enabled: false` causes requests using that key to receive `403`.
- An absent or unknown key receives `401`.
- The first-run default key can be supplied with `BARCODE_API_KEY`.
- Existing keys are loaded from `barcode_data/api_keys.json`.
- API keys are stored as plaintext JSON by the current implementation. Use restricted file permissions and a secret manager for production.

Do not paste real keys into README files, source code, issue reports, logs, or public repositories.

## CLI reference

All commands are run from the repository root.

### Add a product interactively

```bash
python barcode_server.py --add
```

The CLI asks for the barcode, product name, and optional image URL. It can add multiple products for the same barcode, but it rejects an exact duplicate of the same barcode and product name.

### Edit a product interactively

```bash
python barcode_server.py --edit
```

If a barcode has multiple products, the CLI displays a zero-based product index for selection.

### List all products

```bash
python barcode_server.py --list
```

Displays all products in a terminal table.

### Show storage statistics

```bash
python barcode_server.py --stats
```

Displays unique barcode count, total product count, shard count, and the active shard.

### Add an API key

```bash
python barcode_server.py \
  --add-key "NEW_RANDOM_KEY" \
  --name "Mobile App" \
  --limits "lookup:500,image:20,add:10"
```

The limits are numeric requests per second for the relevant dynamic endpoints. The `add` value is stored with the key and is part of the key configuration, although the current route decorators use a fixed limit for add/update requests.

### Remove an API key

```bash
python barcode_server.py --remove-key "NEW_RANDOM_KEY"
```

### List API keys

```bash
python barcode_server.py --list-keys
```

The CLI masks most of each key when displaying it.

## API reference

Base URL:

```text
http://localhost:5000/api
```

### Endpoint summary

| Method | Endpoint | Authentication | Purpose |
|---|---|---:|---|
| `GET` | `/api/` | No | API information and endpoint list |
| `GET` | `/api/lookup/<barcode>` | No | Return all products for a barcode |
| `GET` | `/api/lookup/<barcode>/image` | No | Download the first product's image |
| `POST` | `/api/add` | Yes | Add a product |
| `PUT` | `/api/update/<barcode>` | Yes | Update one product by zero-based index |
| `GET` | `/api/all` | No | Return all products |
| `GET` | `/api/export` | Yes | Download all CSV shards as a ZIP file |
| `GET` | `/api/metrics` | No | Return in-process metrics |

### `GET /api/`

Returns the API description and available endpoints.

```bash
curl http://localhost:5000/api/
```

### `GET /api/lookup/<barcode>`

Returns a `products` array. A barcode can have more than one product.

```bash
curl http://localhost:5000/api/lookup/6281006451865
```

Example response:

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

If the barcode does not exist, the server returns `404`.

### `GET /api/lookup/<barcode>/image`

Downloads the image belonging to the first product in the list. The response is an attachment named after the barcode.

```bash
curl -OJ http://localhost:5000/api/lookup/6281006451865/image
```

This endpoint returns `404` if the barcode has no product or no image URL.

### `POST /api/add`

Requires `X-API-Key` and JSON. `barcode` and `name` are required; `image` is optional.

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

The image is validated synchronously, then its content is prefetched in a background executor.

### `PUT /api/update/<barcode>`

Requires `X-API-Key`. The JSON body must include `index`, which is zero-based within the products array for that barcode. Include `name`, `image`, or both to change them.

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

The update rewrites the CSV shards so they match the JSON index and clears the barcode lookup cache.

### `GET /api/all`

Returns a flattened array containing every product:

```bash
curl http://localhost:5000/api/all
```

Each item includes `barcode`, `product_name`, `image_url`, and `shard`.

### `GET /api/export`

Requires `X-API-Key` and returns `all_shards.zip`:

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  http://localhost:5000/api/export \
  --output all_shards.zip
```

### `GET /api/metrics`

Returns process-local request and cache statistics:

```bash
curl http://localhost:5000/api/metrics
```

Example shape:

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

`total_entries` is the number of unique barcode keys, not the total number of product rows. Metrics reset when the process restarts and are not shared between workers.

### Redirect routes

For compatibility, the application also exposes redirects such as `/`, `/lookup/<barcode>`, `/lookup/<barcode>/image`, `/all`, and `/export`. Prefer the `/api/...` routes for new clients.

## Rate limits

The current route configuration includes:

| Operation | Current limit behavior |
|---|---|
| API home | `30 per second` |
| Lookup | Key-specific `lookup` value per second; otherwise `20 per second` |
| Image download | Key-specific `image` value per second; otherwise `1 per 3 seconds` |
| Add | `5 per second` using the request key/IP as the limiter key |
| Update | `5 per second` using the request key/IP as the limiter key |
| All products | `30 per second` |
| Export | `2 per minute` using the request key/IP as the limiter key |
| Metrics | `10 per minute` |
| Flask-Limiter defaults | `200 per day` and `50 per hour` where no route-specific limit overrides it |

The limiter uses in-memory storage, so rate-limit state is process-local.

## Data storage

### `index.json`

The JSON index maps a barcode to a list of product objects:

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

Products are stored in files named `my_products_0.csv`, `my_products_1.csv`, and so on. Each shard has the columns:

```text
barcode,product_name,image_url
```

A new shard is created after the active shard reaches `10,000` data rows. The application keeps the JSON index in memory for lookups and writes new products to the active CSV shard.

### Multiple products and duplicates

- One barcode may contain multiple products.
- An exact duplicate with the same barcode and product name is rejected.
- The image URL is not part of the duplicate comparison.

### Legacy migration

If a root-level `my_products.csv` exists and `barcode_data/index.json` does not exist, startup migrates its rows into `barcode_data/my_products_0.csv` and creates an index. Existing old single-product index entries are also converted into the current list format.

### Updates

An update modifies the JSON index and then rewrites all CSV shards from the current index. This keeps the two storage representations synchronized, but it can be expensive for large datasets.

## Caching and background work

- Product lookups are cached for `3,600` seconds (one hour).
- Downloaded images are cached for `86,400` seconds (24 hours).
- Adding a product submits image prefetch work to a `ThreadPoolExecutor` with five workers.
- A lookup cache entry is cleared after a product update.
- The cache is an in-memory `SimpleCache`; it is lost on restart and is not shared across processes.

## Security behavior

The current implementation includes the following protections:

- Only `http` and `https` image URLs are accepted.
- Hostnames are resolved and private, loopback, multicast, and link-local IPv4 addresses are rejected.
- The metadata/link-local range beginning with `169.254.` is explicitly blocked.
- Image responses must have an `image/*` content type.
- Images are limited to 5 MiB during validation and streaming download.
- Redirects are not followed for image validation or download.
- CSV values beginning with `+`, `-`, `=`, or `@` are prefixed before being written.
- Protected endpoints require a valid, enabled API key.
- Rate limiting reduces uncontrolled request volume.

These checks are defense-in-depth, not a substitute for network egress controls, a reverse proxy, TLS, secret management, and regular dependency updates.

## Configuration

Configuration is currently defined as constants in `barcode_server.py`:

| Setting | Default | Purpose |
|---|---:|---|
| `DATA_DIR` | `barcode_data` | Runtime data directory |
| `INDEX_FILE` | `barcode_data/index.json` | JSON index path |
| `API_KEYS_FILE` | `barcode_data/api_keys.json` | API-key configuration path |
| `SHARD_LIMIT` | `10000` | Maximum data rows per CSV shard |
| `MAX_IMAGE_SIZE` | `5 * 1024 * 1024` | Maximum image size, 5 MiB |
| Lookup cache timeout | `3600` seconds | Product lookup cache lifetime |
| Image cache timeout | `86400` seconds | Image cache lifetime |
| `PORT` | `5000` in `render.py` | Render-style server port |
| `BARCODE_API_KEY` | unset | First-run default API key source |
| `RENDER_EXTERNAL_URL` | Render URL fallback | Target URL for `render.py` self-ping |

Changing constants requires editing the source file and restarting the application.

## Status codes and errors

| Status | Meaning | Common cause |
|---:|---|---|
| `200` | Success | Valid request |
| `400` | Bad request | Missing JSON, fields, invalid index, duplicate product, or invalid image |
| `401` | Unauthorized | Missing or unknown API key |
| `403` | Forbidden | API key exists but is disabled |
| `404` | Not found | Barcode, image, or resource does not exist |
| `429` | Too many requests | A configured rate limit was exceeded |
| `500` | Server error | Image download or unexpected runtime failure |

Common error responses are JSON objects containing an `error` field.

## Troubleshooting

### `401 Missing X-API-Key header.`

Add the header to protected requests:

```bash
curl -H "X-API-Key: YOUR_API_KEY" http://localhost:5000/api/export
```

### `401 Invalid API Key.`

Check `barcode_data/api_keys.json`, confirm the exact key, and ensure the server is reading the expected `DATA_DIR`.

### `403 API Key is disabled.`

Enable the key in the key configuration or create a new key with the CLI.

### `404 Barcode not found.`

The barcode is matched after trimming whitespace. Confirm that the value exists in `index.json` or add it first.

### `Image validation failed`

Check that the URL is reachable, uses HTTP/HTTPS, returns an `image/*` content type, does not resolve to a private address, and is smaller than 5 MiB.

### `429 Too Many Requests`

Wait for the rate-limit window to reset or use the correct configured key for the application. Do not use artificially unlimited limits in an untrusted environment.

### Data appears out of sync

Stop concurrent writers, back up `barcode_data/`, inspect `index.json` and CSV shards, and restart the application. Updates rewrite all shards, so do not edit the files manually while the server is running.

### Port already in use

Stop the process using port 5000 or use a production server binding to another port:

```bash
gunicorn --bind 0.0.0.0:8000 barcode_server:app
```

## Production notes

- Run behind HTTPS and a reverse proxy or managed ingress.
- Rotate any key that has been committed to Git or exposed in logs.
- Keep `api_keys.json` outside public downloads and restrict its filesystem permissions.
- Back up both `index.json` and every CSV shard together; they represent one dataset.
- Avoid multiple application processes writing to the same local CSV directory without an external coordination strategy.
- The current lock protects writes inside one process only.
- In-memory cache, metrics, and rate-limit state are not shared between workers or instances.
- For larger or highly concurrent deployments, use a database and shared cache/rate-limit backend.
- Validate backups by restoring them to a separate environment.
- Pin and regularly update dependencies after testing compatibility.
- Add automated tests and migration checks before making storage or security changes.

## Contributing

1. Create a feature branch.
2. Make a focused change.
3. Update the documentation and examples when behavior changes.
4. Test the affected CLI/API behavior locally.
5. Open a pull request with a clear description and security impact, if any.

Do not include real API keys, private customer data, or production CSV exports in commits or pull requests.

## License

The project documentation currently identifies the project as `GPL-3.0-or-later`. The repository should include a matching `LICENSE` file so that the licensing terms are unambiguous. Consult the maintainer before redistributing or changing the license declaration.

## Support

For bugs, security concerns, or feature requests, open an issue in the repository. For sensitive security issues, avoid posting credentials or exploit details publicly; contact the maintainer through an appropriate private channel first.
