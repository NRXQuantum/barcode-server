```markdown
# 📦 Secure Barcode API Server

A production-ready, high-performance REST API server for managing product barcodes (EAN/UPC) with multi-key authentication, sharded storage, intelligent caching, and enterprise-grade security.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-black)](https://flask.palletsprojects.com/)

---

## 🚀 Overview

This server acts as a central barcode lookup and data management system. It allows you to store product names and image URLs against barcodes, and serves them via a fast, cache-first API.

Built for scalability, it uses **sharded CSV storage** (auto-rotates after 10k entries), an **in-memory caching layer**, and **async background image prefetching** to ensure lightning-fast responses even with millions of entries.

---

## ✨ Key Features

- 🔑 **Multi-Key Authentication** – Create unique API keys for different apps (Mobile, Admin, Testing) with **per-key rate limits**.
- ⚡ **Dynamic Rate Limiting** – Public IPs get standard limits; verified apps get higher throughput. (Includes an **"Unlimited" test key** for development).
- 🗄️ **Sharded CSV Storage** – Auto-rotates data into multiple CSV files (`my_products_0.csv`, `my_products_1.csv`) to prevent monolithic file bloat.
- 🧠 **Intelligent Caching** – Lookup results cached for 1 hour; downloaded images cached for 24 hours. Second requests are served in milliseconds.
- 🖼️ **Async Image Prefetch** – When a product is added, the image is downloaded and cached **in the background**. The user gets an instant `200 OK` response.
- 🔒 **Enterprise Security**:
  - **SSRF Protection** – Blocks internal/private IPs (192.168.x.x, 10.x.x.x, 169.254.169.254).
  - **CSV Injection Prevention** – Escapes dangerous Excel formulas (`=`, `+`, `-`, `@`).
  - **Image Validation** – Validates content-type, file size (max 5MB), and accessibility before saving.
- 📊 **Monitoring** – Built-in `/api/metrics` endpoint to check cache hit ratio, average response time, and total entries.
- 📥 **ZIP Export** – Download all shard files as a single, compressed ZIP archive.

---

## 🛠️ Tech Stack

- **Python** (3.8+)
- **Flask** – Web framework.
- **Flask-Limiter** – Rate limiting.
- **Flask-Caching** – In-memory caching.
- **Requests** – Async image fetching and validation.

---

## 📥 Installation & Setup

### 1. Clone the Repository (or copy the script)
```bash
git clone <your-repo-url>
cd <your-repo-directory>
```

2. Install Dependencies

```bash
pip install flask flask-limiter flask-caching requests
```

3. Run the Server

```bash
python barcode_server.py
```

The server will start at http://localhost:5000. On the first run, it creates a default admin key and the barcode_data/ directory automatically.

---

🔑 API Key Management (CLI)

Manage keys directly from the terminal without touching the JSON files.

List all keys

```bash
python barcode_server.py --list-keys
```

Add a new application key

```bash
python barcode_server.py --add-key "MyAppKey123" --name "Android App" --limits "lookup:500,image:20,add:10"
```

Add a high-throughput "Unlimited" test key

```bash
python barcode_server.py --add-key "TEST_SUPER_KEY" --name "Dev Test Key" --limits "lookup:99999,image:99999,add:99999"
```

Remove a key

```bash
python barcode_server.py --remove-key "MyAppKey123"
```

Interactive Data Entry (CLI)

```bash
python barcode_server.py --add
```

---

📡 API Endpoints

Base URL: http://localhost:5000/api/

Method Endpoint Description Auth Required
GET / API Home & Endpoint list. No
GET /lookup/<barcode> Get product details (Name, Image URL, Shard). No (Public)
GET /lookup/<barcode>/image Download the product image directly. No (Public)
POST /add Add a new product (JSON Payload). Yes (X-API-Key)
GET /all List all products in the database. No (Rate limited)
GET /export Download all shards as a ZIP file. Yes (X-API-Key)
GET /metrics Server performance & statistics. No

---

🧪 API Usage Examples (cURL)

1. Add a New Product (Requires Key)

```bash
curl -X POST http://localhost:5000/api/add \
  -H "X-API-Key: TEST_SUPER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"barcode":"6281006451865","name":"Vaseline Hair Tonic","image":"https://example.com/hair-tonic.jpg"}'
```

Response:

```json
{"status":"ok","message":"Product added successfully. Image caching in background.","shard":"my_products_0.csv"}
```

2. Lookup a Product (Public)

```bash
curl http://localhost:5000/api/lookup/6281006451865
```

Response:

```json
{"barcode":"6281006451865","product_name":"Vaseline Hair Tonic","image_url":"https://example.com/hair-tonic.jpg","shard":"my_products_0.csv"}
```

3. Download the Product Image (Public)

```bash
# Saves the image as '6281006451865.jpg'
curl -O -J http://localhost:5000/api/lookup/6281006451865/image
```

4. Download All Data as ZIP (Requires Key)

```bash
curl -H "X-API-Key: TEST_SUPER_KEY" http://localhost:5000/api/export --output all_data.zip
```

---

📊 Monitoring & Metrics

Check the server health and performance:

```bash
curl http://localhost:5000/api/metrics
```

Sample Response:

```json
{
  "total_requests": 1250,
  "cache_hits": 1020,
  "cache_misses": 230,
  "cache_hit_ratio": 81.6,
  "avg_response_time_ms": 12.34,
  "active_shard": "my_products_2.csv",
  "total_entries": 23500
}
```

---

⚙️ Configuration

You can modify the following constants inside barcode_server.py:

· SHARD_LIMIT : Number of rows per CSV file (Default: 10000).
· MAX_IMAGE_SIZE : Max file size for images (Default: 5 * 1024 * 1024 = 5MB).
· DATA_DIR : Folder name for storage (Default: barcode_data).

---

🔒 Security Features Explained

Feature Protection
SSRF Protection Blocks requests to localhost, private networks (192.168.x.x, 10.x.x.x), and metadata endpoints (169.254.169.254).
CSV Injection Escapes fields starting with =, +, -, or @ to prevent Excel formula attacks.
Image Validation Checks Content-Type (must start with image/), file size, and URL accessibility.
Rate Limiting Prevents brute-force attacks and DoS. Public: 20/sec. App Keys: Configurable (e.g., 500/sec).

---

📜 License

This project is licensed under the GNU General Public License v3.0.
You are free to:

· Use it commercially.
· Modify and distribute it.

You must: Keep the source code open and include the original license notice.

```
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026
```

---

🤝 Contributing

1. Fork the repository.
2. Create your feature branch (git checkout -b feature/AmazingFeature).
3. Commit your changes (git commit -m 'Add some AmazingFeature').
4. Push to the branch (git push origin feature/AmazingFeature).
5. Open a Pull Request.

---

📞 Support

For issues or questions, please open an issue in the repository or contact the maintainer.

Built with ❤️ for scalability and security.

```
