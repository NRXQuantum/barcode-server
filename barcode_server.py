import sys
import csv
import os
import json
import re
import io
import requests
import glob
import threading
import zipfile
import socket
import ipaddress
import logging
import time
from urllib.parse import urljoin, urlparse
from flask import Flask, request, jsonify, send_file, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from concurrent.futures import ThreadPoolExecutor

# ==================== CONFIGURATION ====================
DATA_DIR = "barcode_data"
INDEX_FILE = os.path.join(DATA_DIR, "index.json")
API_KEYS_FILE = os.path.join(DATA_DIR, "api_keys.json")
AUDIT_LOG_FILE = os.path.join(DATA_DIR, "deletion_audit.log")
SHARD_LIMIT = 10000
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_REDIRECTS = 3
MAX_BATCH_SIZE = 100          # bulk add/lookup max items
MAX_DELETE_INDICES = 50       # max indices per delete call
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 500
IMAGE_MODE = 'redirect'       # 'redirect' (default) or 'proxy'
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== ATOMIC FILE WRITE HELPERS ====================
def _atomic_write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def _count_csv_rows(path):
    try:
        with open(path, 'rb') as f:
            count = 0
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                count += chunk.count(b'\n')
        return max(0, count - 1)
    except OSError:
        return 0

def _audit_log(action, key_name, barcode, indices, ip):
    try:
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        line = f"{ts} | {action} | key={key_name} | barcode={barcode} | indices={indices} | ip={ip}\n"
        with open(AUDIT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception as e:
        logger.warning(f"Audit log write failed: {e}")

# ==================== API KEYS MANAGER (cached) ====================
_api_keys_cache = {'data': None, 'mtime': 0.0}
_api_keys_lock = threading.Lock()

def load_api_keys():
    if not os.path.exists(API_KEYS_FILE):
        default_key = os.environ.get('BARCODE_API_KEY', 'your-strong-api-key-here-12345')
        default_data = {
            default_key: {
                "name": "Default Admin Key",
                "enabled": True,
                "limits": {"lookup": 300, "image": 10, "add": 10}
            }
        }
        _atomic_write_json(API_KEYS_FILE, default_data)
        logger.info(f"Default API key created: {default_key}")
        with _api_keys_lock:
            _api_keys_cache['data'] = default_data
            _api_keys_cache['mtime'] = os.path.getmtime(API_KEYS_FILE)
        return default_data

    mtime = os.path.getmtime(API_KEYS_FILE)
    with _api_keys_lock:
        if _api_keys_cache['data'] is not None and _api_keys_cache['mtime'] == mtime:
            return _api_keys_cache['data']
    with open(API_KEYS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    with _api_keys_lock:
        _api_keys_cache['data'] = data
        _api_keys_cache['mtime'] = mtime
    return data

def save_api_keys(keys_data):
    _atomic_write_json(API_KEYS_FILE, keys_data)
    with _api_keys_lock:
        _api_keys_cache['data'] = keys_data
        try:
            _api_keys_cache['mtime'] = os.path.getmtime(API_KEYS_FILE)
        except OSError:
            _api_keys_cache['mtime'] = 0.0

def add_new_api_key(key, name, limits=None):
    keys = load_api_keys()
    if key in keys:
        return False, "Key already exists."
    keys[key] = {
        "name": name,
        "enabled": True,
        "limits": limits or {"lookup": 200, "image": 5, "add": 5}
    }
    save_api_keys(keys)
    return True, "Key added successfully."

def remove_api_key(key):
    keys = load_api_keys()
    if key not in keys:
        return False, "Key not found."
    del keys[key]
    save_api_keys(keys)
    return True, "Key removed."

def get_key_limits(key):
    keys = load_api_keys()
    if key in keys:
        return keys[key].get('limits', {})
    return {}

# ==================== FLASK APP & EXTENSIONS ====================
app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 3600})
executor = ThreadPoolExecutor(max_workers=5)

_app_start_time = time.time()

# ==================== MONITORING METRICS (thread-safe) ====================
metrics = {
    'total_requests': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'avg_response_time': 0,
    'request_times': []
}
metrics_lock = threading.Lock()

def update_metrics(start_time, cache_hit=False):
    elapsed = (time.time() - start_time) * 1000
    with metrics_lock:
        metrics['total_requests'] += 1
        if cache_hit:
            metrics['cache_hits'] += 1
        else:
            metrics['cache_misses'] += 1
        metrics['request_times'].append(elapsed)
        if len(metrics['request_times']) > 1000:
            metrics['request_times'].pop(0)
        metrics['avg_response_time'] = sum(metrics['request_times']) / len(metrics['request_times'])

def snapshot_metrics():
    with metrics_lock:
        return {
            'total_requests': metrics['total_requests'],
            'cache_hits': metrics['cache_hits'],
            'cache_misses': metrics['cache_misses'],
            'avg_response_time': metrics['avg_response_time'],
        }

# ==================== SECURITY HELPERS ====================
def sanitize_csv_field(value):
    if isinstance(value, str) and value and value[0] in '+-=@':
        return "'" + value
    return value

def is_safe_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False, "Only HTTP/HTTPS protocols are allowed."
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid hostname."
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False, "Cannot resolve hostname."
        for addr in addr_info:
            ip_str = addr[4][0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                return False, "Invalid IP address format."
            if (ip_obj.is_private or ip_obj.is_loopback or
                ip_obj.is_multicast or ip_obj.is_link_local or
                ip_obj.is_reserved or ip_obj.is_unspecified):
                return False, f"Private/Internal IP address not allowed: {ip_str}"
        return True, None
    except Exception as e:
        return False, f"Security check failed: {str(e)}"

def _safe_fetch_head(url, timeout=5, max_redirects=MAX_REDIRECTS):
    current = url
    for _ in range(max_redirects + 1):
        safe, msg = is_safe_url(current)
        if not safe:
            return None, msg
        try:
            resp = requests.head(current, timeout=timeout, allow_redirects=False)
        except requests.exceptions.Timeout:
            return None, "Request timeout."
        except requests.exceptions.ConnectionError:
            return None, "Connection failed."
        except Exception as e:
            return None, f"Request error: {e}"

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get('location')
            if not location:
                return None, "Redirect without Location header."
            current = urljoin(current, location)
            continue
        return resp, None
    return None, "Too many redirects."

def validate_image_url(url, timeout=5):
    if not url:
        return False, "URL is empty."
    resp, err = _safe_fetch_head(url, timeout=timeout)
    if err:
        return False, err
    if resp.status_code != 200:
        return False, f"HTTP error: {resp.status_code}"
    content_type = resp.headers.get('content-type', '')
    if not content_type.startswith('image/'):
        return False, f"Invalid content type: {content_type}. Only images are allowed."
    content_length = resp.headers.get('content-length')
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_SIZE:
                return False, f"Image exceeds maximum size limit ({MAX_IMAGE_SIZE} bytes)."
        except ValueError:
            pass
    return True, None

def download_safe_image(url, timeout=10, max_redirects=MAX_REDIRECTS):
    current = url
    resp = None
    for _ in range(max_redirects + 1):
        safe, msg = is_safe_url(current)
        if not safe:
            raise ValueError(f"URL blocked: {msg}")
        try:
            resp = requests.get(current, timeout=timeout, stream=True, allow_redirects=False)
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {e}")

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get('location')
            if not location:
                raise Exception("Redirect without Location header.")
            current = urljoin(current, location)
            continue
        break
    else:
        raise Exception("Too many redirects.")

    if resp.status_code != 200:
        raise Exception(f"HTTP error {resp.status_code}")
    content_type = resp.headers.get('content-type', '')
    if not content_type.startswith('image/'):
        raise Exception(f"Invalid content type: {content_type}")
    downloaded = 0
    content = b''
    for chunk in resp.iter_content(chunk_size=8192):
        content += chunk
        downloaded += len(chunk)
        if downloaded > MAX_IMAGE_SIZE:
            raise Exception("Image download exceeded size limit.")
    return content, content_type

# ==================== DATABASE CLASS ====================
class BarcodeDB:
    def __init__(self):
        self.index = {}
        self.active_shard = None
        self.active_count = 0
        self.lock = threading.Lock()
        self._initialize()

    def _initialize(self):
        legacy_file = 'my_products.csv'
        if os.path.exists(legacy_file) and not os.path.exists(INDEX_FILE):
            logger.info("Migrating from legacy my_products.csv ...")
            with open(legacy_file, 'r', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            if rows:
                shard_name = os.path.join(DATA_DIR, "my_products_0.csv")
                with open(shard_name, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['barcode', 'product_name', 'image_url'])
                    for row in rows:
                        writer.writerow([row['barcode'], row['product_name'], row['image_url']])
                        bc = row['barcode']
                        if bc not in self.index:
                            self.index[bc] = []
                        self.index[bc].append({
                            'name': row['product_name'],
                            'image': row['image_url'],
                            'shard': os.path.basename(shard_name)
                        })
                _atomic_write_json(INDEX_FILE, self.index)
                logger.info(f"Migration complete. {len(rows)} entries moved.")

        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data and isinstance(next(iter(data.values())), dict):
                logger.info("Converting old index format to multi-product format...")
                new_index = {}
                for bc, prod in data.items():
                    new_index[bc] = [prod]
                self.index = new_index
                _atomic_write_json(INDEX_FILE, self.index)
                logger.info("Conversion complete.")
            else:
                self.index = data

        shard_files = glob.glob(os.path.join(DATA_DIR, "my_products_*.csv"))
        if not shard_files:
            self._create_new_shard()
        else:
            shard_files.sort(key=lambda x: int(x.split('_')[-1].split('.')[0]))
            self.active_shard = shard_files[-1]
            self.active_count = _count_csv_rows(self.active_shard)
            if self.active_count >= SHARD_LIMIT:
                self._create_new_shard()

    def _create_new_shard(self):
        existing = glob.glob(os.path.join(DATA_DIR, "my_products_*.csv"))
        next_idx = len(existing)
        shard_path = os.path.join(DATA_DIR, f"my_products_{next_idx}.csv")
        with open(shard_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['barcode', 'product_name', 'image_url'])
        self.active_shard = shard_path
        self.active_count = 0
        logger.info(f"New shard created: {os.path.basename(shard_path)}")

    def _extract_url(self, text):
        if not text:
            return ''
        match = re.search(r'https?://[^\s"\'<>]+', text)
        if not match:
            return text.strip()
        url = match.group(0)
        url = re.sub(r'[.,;:!?)\]\}]+$', '', url)
        return url

    def _cache_image_async(self, img_url, barcode):
        try:
            content, content_type = download_safe_image(img_url)
            cache.set(f"img_{barcode}", (content, content_type), timeout=86400)
            logger.info(f"Background cache ready for {barcode}")
        except Exception as e:
            logger.warning(f"Background caching failed for {barcode}: {e}")

    # ---------- ADD ----------
    def add(self, barcode, name, image, validate=True):
        clean_img = self._extract_url(image)
        safe_barcode = sanitize_csv_field(barcode)
        safe_name = sanitize_csv_field(name)
        raw_barcode = barcode.strip()

        if validate and clean_img:
            is_valid, err_msg = validate_image_url(clean_img)
            if not is_valid:
                return False, f"Image validation failed: {err_msg}"

        with self.lock:
            if raw_barcode in self.index:
                for prod in self.index[raw_barcode]:
                    if prod['name'] == safe_name:
                        return False, f"Product with barcode '{raw_barcode}' and name '{safe_name}' already exists."

            if raw_barcode not in self.index:
                self.index[raw_barcode] = []

            new_product = {
                'name': safe_name,
                'image': clean_img,
                'shard': os.path.basename(self.active_shard)
            }
            self.index[raw_barcode].append(new_product)

            if self.active_count >= SHARD_LIMIT:
                self._create_new_shard()
            with open(self.active_shard, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([safe_barcode, safe_name, clean_img])
            self.active_count += 1

            _atomic_write_json(INDEX_FILE, self.index)

            if clean_img:
                executor.submit(self._cache_image_async, clean_img, raw_barcode)

            logger.info(f"Product added: {raw_barcode} -> {safe_name}")
            return True, "OK"

    # ---------- UPDATE ----------
    def update(self, barcode, product_index, new_name=None, new_image=None, validate=True):
        raw_barcode = barcode.strip()
        with self.lock:
            if raw_barcode not in self.index:
                return False, f"Barcode '{raw_barcode}' not found.", None

            products = self.index[raw_barcode]
            if product_index < 0 or product_index >= len(products):
                return False, f"Invalid product index. Must be between 0 and {len(products)-1}.", None

            prod = products[product_index]

            if new_name is not None and new_name.strip() != '':
                final_name = sanitize_csv_field(new_name.strip())
            else:
                final_name = prod['name']

            if new_image is not None and new_image.strip() != '':
                clean_img = self._extract_url(new_image)
                if validate and clean_img:
                    is_valid, err_msg = validate_image_url(clean_img)
                    if not is_valid:
                        return False, f"Image validation failed: {err_msg}", None
                final_image = clean_img
            else:
                final_image = prod['image']

            if final_name == prod['name'] and final_image == prod['image']:
                return False, "No changes detected.", None

            prod['name'] = final_name
            prod['image'] = final_image

            _atomic_write_json(INDEX_FILE, self.index)
            self._rewrite_all_shards()

            cache.delete(raw_barcode)
            cache.delete(f"img_{raw_barcode}")

            logger.info(f"Product updated: {raw_barcode} index {product_index} -> {final_name}")
            return True, "Update successful.", prod

    # ---------- DELETE (index-based, one or many) ----------
    def delete(self, barcode, indices):
        """
        Delete one or more products from a barcode by index.
        Cannot delete the barcode itself, only products under it.
        Returns (success, message, details_list).
        """
        raw_barcode = barcode.strip()
        with self.lock:
            if raw_barcode not in self.index:
                return False, f"Barcode '{raw_barcode}' not found.", []

            products = self.index[raw_barcode]

            # Validate all indices are integers and in-range
            invalid = []
            for i in indices:
                if not isinstance(i, int) or i < 0 or i >= len(products):
                    invalid.append(i)
            if invalid:
                return False, f"Invalid index/indices: {invalid}. Valid range: 0..{len(products)-1}", []

            # Dedupe and sort descending so pops don't shift each other
            unique_desc = sorted(set(indices), reverse=True)

            details = []
            for i in unique_desc:
                removed = products.pop(i)
                details.append({
                    "index": i,
                    "status": "deleted",
                    "name": removed.get('name', '')
                })

            # If this barcode now has no products, remove the key entirely
            if len(products) == 0:
                del self.index[raw_barcode]

            _atomic_write_json(INDEX_FILE, self.index)
            self._rewrite_all_shards()

            cache.delete(raw_barcode)
            cache.delete(f"img_{raw_barcode}")

            # Sort details ascending for readable output
            details.sort(key=lambda d: d['index'])
            logger.info(f"Deleted {len(details)} product(s) from barcode {raw_barcode}")
            return True, "OK", details

    def _rewrite_all_shards(self):
        all_products = self.get_all()

        shard_contents = []
        batch = []
        for prod in all_products:
            batch.append([prod['barcode'], prod['product_name'], prod['image_url']])
            if len(batch) >= SHARD_LIMIT:
                shard_contents.append(batch)
                batch = []
        if batch:
            shard_contents.append(batch)
        if not shard_contents:
            shard_contents.append([])

        for idx, rows in enumerate(shard_contents):
            self._write_shard_from_list(idx, rows)

        existing = sorted(
            glob.glob(os.path.join(DATA_DIR, "my_products_*.csv")),
            key=lambda x: int(x.split('_')[-1].split('.')[0])
        )
        for extra in existing[len(shard_contents):]:
            try:
                os.remove(extra)
            except OSError as e:
                logger.warning(f"Failed to remove extra shard {extra}: {e}")

        if shard_contents:
            self.active_shard = os.path.join(DATA_DIR, f"my_products_{len(shard_contents)-1}.csv")
            self.active_count = len(shard_contents[-1])
        else:
            self._create_new_shard()

    def _write_shard_from_list(self, idx, rows):
        shard_path = os.path.join(DATA_DIR, f"my_products_{idx}.csv")
        tmp = shard_path + '.tmp'
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['barcode', 'product_name', 'image_url'])
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, shard_path)

    def lookup(self, barcode):
        raw = barcode.strip()
        return self.index.get(raw, [])

    def get_all(self):
        all_products = []
        for bc, products in self.index.items():
            for prod in products:
                all_products.append({
                    'barcode': bc,
                    'product_name': prod['name'],
                    'image_url': prod['image'],
                    'shard': prod['shard']
                })
        return all_products

db = BarcodeDB()

# ==================== AUTH & DYNAMIC LIMIT DECORATORS ====================
def require_api_key(f):
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if not key:
            logger.warning(f"Missing API Key from {request.remote_addr}")
            return jsonify({"error": "Missing X-API-Key header."}), 401
        api_keys = load_api_keys()
        if key not in api_keys:
            logger.warning(f"Invalid API Key attempt from {request.remote_addr}")
            return jsonify({"error": "Invalid API Key."}), 401
        if not api_keys[key].get('enabled', True):
            logger.warning(f"Disabled API Key used: {key[:10]}...")
            return jsonify({"error": "API Key is disabled."}), 403
        request.api_key_limits = api_keys[key].get('limits', {})
        request.api_key_name = api_keys[key].get('name', 'Unknown')
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

def get_custom_key():
    return request.headers.get('X-API-Key', request.remote_addr)

def get_lookup_limit():
    key = request.headers.get('X-API-Key')
    if key:
        limits = get_key_limits(key)
        return f"{limits.get('lookup', 200)} per second"
    return "20 per second"

def get_image_limit():
    key = request.headers.get('X-API-Key')
    if key:
        limits = get_key_limits(key)
        return f"{limits.get('image', 5)} per second"
    return "1 per 3 seconds"

def get_add_limit():
    key = request.headers.get('X-API-Key')
    if key:
        limits = get_key_limits(key)
        return f"{limits.get('add', 5)} per second"
    return "5 per second"

# ==================== PAGINATION HELPER ====================
def _paginate(items, page, per_page):
    total = len(items)
    total_pages = (total + per_page - 1) // per_page if per_page else 1
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total, total_pages

def _parse_pagination():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = int(request.args.get('per_page', DEFAULT_PER_PAGE))
        per_page = min(MAX_PER_PAGE, max(1, per_page))
    except (ValueError, TypeError):
        per_page = DEFAULT_PER_PAGE
    return page, per_page

# ==================== FLASK ROUTES ====================
@app.route('/api/')
@limiter.limit("30 per second")
def api_home():
    return jsonify({
        "message": "Multi-Product Barcode API (supports edit/update/delete/batch/search)",
        "auth": "Provide X-API-Key header for protected endpoints.",
        "endpoints": {
            "GET /api/lookup/<barcode>": "Public (list of products)",
            "GET /api/lookup/<barcode>/image": "Public (302 redirect; ?proxy=1 to stream)",
            "POST /api/lookup-batch": "Public (bulk lookup)",
            "POST /api/add": "🔒 Requires Key",
            "POST /api/add-batch": "🔒 Requires Key (bulk add)",
            "PUT /api/update/<barcode>": "🔒 Requires Key",
            "DELETE /api/delete/<barcode>": "🔒 Requires Key + X-Confirm-Delete: YES-DELETE",
            "GET /api/all": "Public (page=1&per_page=50 for paginated)",
            "GET /api/search?q=<text>": "Public (search name or barcode)",
            "GET /api/export": "🔒 Requires Key (ZIP download)",
            "GET /api/metrics": "Public (server performance)",
            "GET /api/stats": "Public (JSON stats)",
            "GET /api/health": "Public (health check)"
        }
    })

# ---------- ADD (single) ----------
@app.route('/api/add', methods=['POST'])
@limiter.limit(get_add_limit, key_func=get_custom_key)
@require_api_key
def api_add_product():
    start = time.time()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Send JSON payload."}), 400
    barcode = data.get('barcode')
    name = data.get('name')
    if not barcode or not name:
        return jsonify({"error": "Barcode and Name are required fields."}), 400
    success, msg = db.add(barcode, name, data.get('image', ''), validate=True)
    if not success:
        return jsonify({"error": msg}), 400
    logger.info(f"Product added by key: {getattr(request, 'api_key_name', 'Unknown')}")
    update_metrics(start)
    return jsonify({
        "status": "ok",
        "message": "Product added successfully. Image caching in background.",
        "shard": os.path.basename(db.active_shard)
    })

# ---------- ADD (batch) ----------
@app.route('/api/add-batch', methods=['POST'])
@limiter.limit(get_add_limit, key_func=get_custom_key)
@require_api_key
def api_add_batch():
    start = time.time()
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "Body must be a JSON array."}), 400
    if len(data) == 0:
        return jsonify({"error": "Empty array."}), 400
    if len(data) > MAX_BATCH_SIZE:
        return jsonify({"error": f"Maximum {MAX_BATCH_SIZE} items per batch."}), 400

    added = 0
    failed = 0
    results = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            results.append({"index": i, "status": "error", "reason": "Not an object"})
            failed += 1
            continue
        barcode = item.get('barcode')
        name = item.get('name')
        if not barcode or not name:
            results.append({"index": i, "status": "error", "reason": "Missing barcode or name"})
            failed += 1
            continue
        ok, msg = db.add(barcode, name, item.get('image', ''), validate=True)
        if ok:
            results.append({"index": i, "status": "added", "barcode": barcode})
            added += 1
        else:
            results.append({"index": i, "status": "error", "reason": msg})
            failed += 1

    update_metrics(start)
    return jsonify({"added": added, "failed": failed, "results": results})

# ---------- UPDATE ----------
@app.route('/api/update/<barcode>', methods=['PUT'])
@limiter.limit(get_add_limit, key_func=get_custom_key)
@require_api_key
def api_update_product(barcode):
    start = time.time()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Send JSON payload."}), 400

    product_index = data.get('index')
    if product_index is None:
        return jsonify({"error": "Product index is required."}), 400
    try:
        idx = int(product_index)
    except (ValueError, TypeError):
        return jsonify({"error": "Index must be an integer."}), 400

    new_name = data.get('name')
    new_image = data.get('image')

    success, msg, updated = db.update(barcode, idx, new_name, new_image, validate=True)
    if not success:
        return jsonify({"error": msg}), 400

    update_metrics(start)
    return jsonify({
        "status": "ok",
        "message": "Product updated successfully.",
        "updated_product": updated
    })

# ---------- DELETE (one or many indices, API key + confirm header) ----------
@app.route('/api/delete/<barcode>', methods=['DELETE'])
@limiter.limit("5 per minute", key_func=get_custom_key)
@require_api_key
def api_delete_product(barcode):
    start = time.time()

    # Extra safety: confirmation header mandatory
    if request.headers.get('X-Confirm-Delete') != 'YES-DELETE':
        return jsonify({
            "error": "Missing or invalid X-Confirm-Delete header. "
                     "Set to 'YES-DELETE' to confirm deletion."
        }), 400

    data = request.get_json(silent=True)
    if not data or 'indices' not in data:
        return jsonify({"error": "Body must contain 'indices' array."}), 400

    indices = data.get('indices')
    if not isinstance(indices, list) or len(indices) == 0:
        return jsonify({"error": "'indices' must be a non-empty list."}), 400
    if len(indices) > MAX_DELETE_INDICES:
        return jsonify({"error": f"Maximum {MAX_DELETE_INDICES} indices per request."}), 400

    success, msg, details = db.delete(barcode, indices)

    # Audit log regardless of success
    _audit_log(
        action="delete" if success else "delete_failed",
        key_name=getattr(request, 'api_key_name', 'Unknown'),
        barcode=barcode,
        indices=indices,
        ip=request.remote_addr
    )

    update_metrics(start)

    if not success:
        return jsonify({"error": msg}), 400

    return jsonify({
        "status": "ok",
        "deleted": len(details),
        "details": details
    })

# ---------- LOOKUP (single) ----------
@app.route('/api/lookup/<barcode>')
@limiter.limit(get_lookup_limit, key_func=get_custom_key)
def api_lookup_product(barcode):
    start = time.time()
    cached = cache.get(barcode)
    if cached is not None:
        update_metrics(start, cache_hit=True)
        return jsonify({"barcode": barcode, "products": cached})

    products = db.lookup(barcode)
    if products:
        cache.set(barcode, products, timeout=3600)
        update_metrics(start, cache_hit=False)
        return jsonify({"barcode": barcode, "products": products})
    update_metrics(start)
    return jsonify({"error": "Barcode not found."}), 404

# ---------- LOOKUP (batch) ----------
@app.route('/api/lookup-batch', methods=['POST'])
@limiter.limit(get_lookup_limit, key_func=get_custom_key)
def api_lookup_batch():
    start = time.time()
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"error": "Body must be a JSON array of barcodes."}), 400
    if len(data) == 0:
        return jsonify({"error": "Empty array."}), 400
    if len(data) > MAX_BATCH_SIZE:
        return jsonify({"error": f"Maximum {MAX_BATCH_SIZE} barcodes per batch."}), 400

    results = {}
    for bc in data:
        if not isinstance(bc, str):
            continue
        products = db.lookup(bc)
        results[bc] = products if products else None

    update_metrics(start)
    return jsonify(results)

# ---------- IMAGE (hybrid: redirect default, ?proxy=1 stream) ----------
@app.route('/api/lookup/<barcode>/image')
@limiter.limit(get_image_limit, key_func=get_custom_key)
def api_download_image(barcode):
    start = time.time()
    products = db.lookup(barcode)
    if not products:
        return jsonify({"error": "Barcode not found."}), 404
    first = products[0]
    img_url = first.get('image', '')
    if not img_url:
        return jsonify({"error": "No image associated with this product."}), 404

    # Proxy fallback mode (heavy but always works)
    use_proxy = (request.args.get('proxy') == '1') or (IMAGE_MODE == 'proxy')
    if use_proxy:
        cached_img = cache.get(f"img_{barcode}")
        if cached_img:
            content, content_type = cached_img
            update_metrics(start, cache_hit=True)
            return send_file(
                io.BytesIO(content),
                mimetype=content_type,
                as_attachment=False,
                download_name=f"{barcode}.jpg"
            )
        try:
            content, content_type = download_safe_image(img_url)
            cache.set(f"img_{barcode}", (content, content_type), timeout=86400)
            update_metrics(start, cache_hit=False)
            return send_file(
                io.BytesIO(content),
                mimetype=content_type,
                as_attachment=False,
                download_name=f"{barcode}.jpg"
            )
        except Exception as e:
            logger.error(f"Image proxy failed: {e}")
            return jsonify({"error": f"Failed to download image: {str(e)}"}), 500

    # Default: 302 redirect (lightweight, no server load)
    update_metrics(start)
    return redirect(img_url, code=302)

# ---------- ALL (backward compatible + pagination) ----------
@app.route('/api/all')
@limiter.limit("30 per second")
def api_all_products():
    start = time.time()

    # Backward compat: no page/per_page → old flat array
    if 'page' not in request.args and 'per_page' not in request.args:
        data = db.get_all()
        update_metrics(start)
        return jsonify(data)

    page, per_page = _parse_pagination()
    all_products = db.get_all()
    items, total, total_pages = _paginate(all_products, page, per_page)
    update_metrics(start)
    return jsonify({
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "items": items
    })

# ---------- SEARCH ----------
@app.route('/api/search')
@limiter.limit("30 per second")
def api_search():
    start = time.time()

    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required."}), 400

    q_lower = q.lower()
    page, per_page = _parse_pagination()

    matches = []
    for bc, plist in db.index.items():
        bc_match = q_lower in bc.lower()
        for prod in plist:
            name_match = q_lower in prod['name'].lower()
            if bc_match or name_match:
                matches.append({
                    'barcode': bc,
                    'product_name': prod['name'],
                    'image_url': prod['image'],
                    'shard': prod['shard']
                })

    items, total, total_pages = _paginate(matches, page, per_page)
    update_metrics(start)
    return jsonify({
        "query": q,
        "page": page,
        "per_page": per_page,
        "total_matches": total,
        "total_pages": total_pages,
        "items": items
    })

# ---------- EXPORT ----------
@app.route('/api/export')
@limiter.limit("2 per minute", key_func=get_custom_key)
@require_api_key
def api_export_zip():
    start = time.time()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        shard_files = glob.glob(os.path.join(DATA_DIR, "my_products_*.csv"))
        if not shard_files:
            zipf.writestr('empty.txt', 'No data available.')
        else:
            for shard_path in shard_files:
                arcname = os.path.basename(shard_path)
                zipf.write(shard_path, arcname)
    zip_buffer.seek(0)
    update_metrics(start)
    logger.info(f"Export ZIP downloaded by key: {getattr(request, 'api_key_name', 'Unknown')}")
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='all_shards.zip'
    )

# ---------- METRICS ----------
@app.route('/api/metrics')
@limiter.limit("10 per minute")
def get_metrics():
    snap = snapshot_metrics()
    return jsonify({
        "total_requests": snap['total_requests'],
        "cache_hits": snap['cache_hits'],
        "cache_misses": snap['cache_misses'],
        "cache_hit_ratio": round(snap['cache_hits'] / max(1, snap['total_requests']) * 100, 2),
        "avg_response_time_ms": round(snap['avg_response_time'], 2),
        "active_shard": os.path.basename(db.active_shard),
        "total_entries": len(db.index)
    })

# ---------- STATS (JSON) ----------
@app.route('/api/stats')
@limiter.limit("30 per second")
def api_stats():
    def _shard_num(p):
        m = re.search(r'_(\d+)\.csv$', p)
        return int(m.group(1)) if m else 0

    shard_files = sorted(
        glob.glob(os.path.join(DATA_DIR, "my_products_*.csv")),
        key=_shard_num
    )

    total_products = sum(len(p) for p in db.index.values())
    products_with_image = sum(
        1 for plist in db.index.values() for p in plist if p.get('image')
    )

    def _size(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0

    index_size = _size(INDEX_FILE)
    keys_size = _size(API_KEYS_FILE)
    shard_sizes = [(os.path.basename(sf), _size(sf)) for sf in shard_files]
    total_size = index_size + keys_size + sum(s for _, s in shard_sizes)

    try:
        kd = load_api_keys()
        total_keys = len(kd)
        enabled_keys = sum(1 for v in kd.values() if v.get('enabled', True))
    except Exception:
        total_keys = enabled_keys = 0

    return jsonify({
        "products": {
            "unique_barcodes": len(db.index),
            "total_products": total_products,
            "with_image": products_with_image,
            "without_image": total_products - products_with_image,
            "avg_per_barcode": round(total_products / max(1, len(db.index)), 2)
        },
        "storage": {
            "data_dir": DATA_DIR,
            "total_size_bytes": total_size,
            "index_size_bytes": index_size,
            "api_keys_size_bytes": keys_size,
            "total_shards": len(shard_files),
            "shards": [{"name": n, "size_bytes": s} for n, s in shard_sizes]
        },
        "active_shard": {
            "name": os.path.basename(db.active_shard) if db.active_shard else None,
            "rows": db.active_count,
            "limit": SHARD_LIMIT
        },
        "api_keys": {
            "total": total_keys,
            "enabled": enabled_keys,
            "disabled": total_keys - enabled_keys
        }
    })

# ---------- HEALTH ----------
@app.route('/api/health')
@limiter.limit("60 per minute")
def api_health():
    uptime_seconds = int(time.time() - _app_start_time)
    hours = uptime_seconds // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    shards = glob.glob(os.path.join(DATA_DIR, "my_products_*.csv"))
    return jsonify({
        "status": "ok",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": uptime_seconds,
        "shards": len(shards),
        "barcodes": len(db.index),
        "active_shard": os.path.basename(db.active_shard) if db.active_shard else None
    })

# ==================== REDIRECTS (backward compat) ====================
@app.route('/')
def home(): return redirect('/api/')
@app.route('/lookup/<barcode>')
def redirect_lookup(barcode): return redirect(f'/api/lookup/{barcode}')
@app.route('/lookup/<barcode>/image')
def redirect_image(barcode): return redirect(f'/api/lookup/{barcode}/image')
@app.route('/add', methods=['POST'])
def redirect_add(): return api_add_product()
@app.route('/all')
def redirect_all(): return redirect('/api/all')
@app.route('/export')
def redirect_export(): return redirect('/api/export')

# ==================== CLI INTERACTIVE EDIT ====================
def interactive_edit():
    print("\n--- Edit Product (Update name or image) ---")
    barcode = input("Enter barcode to edit: ").strip()
    if not barcode:
        print("❌ Barcode cannot be empty.")
        return

    products = db.lookup(barcode)
    if not products:
        print(f"❌ No products found for barcode '{barcode}'.")
        return

    if len(products) == 1:
        idx = 0
        prod = products[0]
        print(f"\n📦 Editing single product:")
        print(f"  Name : {prod['name']}")
        print(f"  Image: {prod['image']}")
    else:
        print(f"\n📋 Found {len(products)} products for barcode '{barcode}':")
        for i, p in enumerate(products):
            print(f"  [{i}] {p['name']} (Image: {p['image'][:50]}...)")
        try:
            idx = int(input("Select product index to edit: ").strip())
            if idx < 0 or idx >= len(products):
                print("❌ Invalid index.")
                return
        except ValueError:
            print("❌ Please enter a valid number.")
            return
        prod = products[idx]

    print(f"\n📌 Current data for selected product:")
    print(f"  Name : {prod['name']}")
    print(f"  Image: {prod['image']}")

    new_name = input("\nNew name (press Enter to keep unchanged): ").strip()
    new_image = input("New image URL (press Enter to keep unchanged): ").strip()

    if not new_name and not new_image:
        print("ℹ️ No changes provided. Exiting.")
        return

    success, msg, updated = db.update(barcode, idx, new_name, new_image, validate=True)
    if success:
        print(f"✅ {msg}")
        print(f"📦 Updated product: {updated}")
    else:
        print(f"❌ Failed: {msg}")

# ==================== CLI LIST ALL PRODUCTS ====================
def list_all_products():
    products = db.get_all()
    if not products:
        print("\n📭 No products found in the database.")
        return

    print(f"\n📋 Total Products: {len(products)}")
    print("=" * 150)
    print(f"{'Barcode':<20} | {'Product Name':<50} | {'Image URL'}")
    print("-" * 150)

    for p in products:
        barcode = p['barcode']
        name = p['product_name']
        image = p['image_url']
        if len(name) > 48:
            name = name[:45] + "..."
        print(f"{barcode:<20} | {name:<50} | {image}")

    print("=" * 150)
    print(f"✅ Total {len(products)} products displayed.")

# ==================== CLI MANAGEMENT ====================
def interactive_add():
    while True:
        print("\n--- Add New Product (supports multiple products per barcode) ---")
        barcode = input("Barcode: ").strip()
        if not barcode: continue
        name = input("Product Name: ").strip()
        if not name: continue
        image = input("Image URL (optional): ").strip()
        print("⏳ Validating and queuing background cache...")
        success, msg = db.add(barcode, name, image, validate=True)
        if success:
            print(f"✅ Added successfully! (Shard: {os.path.basename(db.active_shard)})")
        else:
            print(f"❌ Failed: {msg}")
        if input("Add another? (y/n): ").strip().lower() != 'y':
            break

def show_stats():
    """Display a clean, standard-level statistics dashboard."""

    class C:
        R  = '\033[0m'
        B  = '\033[1m'
        D  = '\033[2m'
        CY = '\033[36m'
        GR = '\033[32m'
        YE = '\033[33m'
        RE = '\033[31m'
        BL = '\033[34m'
        MA = '\033[35m'
        GY = '\033[90m'
        WH = '\033[97m'

    ANSI_RE = re.compile(r'\033\[[0-9;]*m')
    def _vis(s):
        return len(ANSI_RE.sub('', s))

    def _shard_num(path):
        m = re.search(r'_(\d+)\.csv$', path)
        return int(m.group(1)) if m else 0

    shard_files = sorted(
        glob.glob(os.path.join(DATA_DIR, "my_products_*.csv")),
        key=_shard_num
    )

    total_barcodes = len(db.index)
    total_products = 0
    products_with_image = 0
    barcodes_multi = 0
    barcode_counts = []
    for bc, plist in db.index.items():
        c = len(plist)
        total_products += c
        barcode_counts.append((bc, c))
        if c > 1:
            barcodes_multi += 1
        for p in plist:
            if p.get('image'):
                products_with_image += 1

    products_without_image = total_products - products_with_image
    avg_per_bc = (total_products / total_barcodes) if total_barcodes else 0
    max_bc = max(barcode_counts, key=lambda x: x[1]) if barcode_counts else None

    def _size(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0

    def _human(n):
        for u in ('B', 'KB', 'MB', 'GB', 'TB'):
            if n < 1024:
                return f"{n:.1f} {u}"
            n /= 1024
        return f"{n:.1f} PB"

    index_size = _size(INDEX_FILE)
    keys_size  = _size(API_KEYS_FILE)
    shard_sizes = [(os.path.basename(sf), _size(sf)) for sf in shard_files]
    total_size = index_size + keys_size + sum(s for _, s in shard_sizes)

    try:
        kd = load_api_keys()
        total_keys    = len(kd)
        enabled_keys  = sum(1 for v in kd.values() if v.get('enabled', True))
        disabled_keys = total_keys - enabled_keys
    except Exception:
        total_keys = enabled_keys = disabled_keys = 0

    WIDTH = 64

    def gradient():
        left  = '▁▂▃▄▅▆▇'
        right = '▇▆▅▄▃▂▁'
        fill = WIDTH - len(left) - len(right)
        return f"{C.CY}{left}{'█' * fill}{right}{C.R}"

    def section(symbol, title):
        label = f"  {symbol}  {title}  "
        pad = WIDTH - len(label)
        if pad < 2:
            pad = 2
        left = pad // 2
        right = pad - left
        return (f"{C.GY}{'─' * left}{C.R}"
                f"{C.CY}{C.B}{label}{C.R}"
                f"{C.GY}{'─' * right}{C.R}")

    def leader(label, value, vcolor=C.CY, label_color=C.GY, label_w=22):
        return (f"    {label_color}{label:<{label_w}}{C.R}"
                f" {C.GY}:{C.R} "
                f"{vcolor}{C.B}{value}{C.R}")

    def center(text):
        pad = WIDTH - _vis(text)
        if pad < 0:
            pad = 0
        left = pad // 2
        right = pad - left
        return f"{' ' * left}{text}{' ' * right}"

    print()
    print(gradient())
    print(center(
        f"{C.CY}❰{C.R}  {C.CY}◆{C.R}  "
        f"{C.WH}{C.B}BARCODE SERVER STATISTICS{C.R}  "
        f"{C.CY}❱{C.R}"
    ))
    print(gradient())
    print()

    print(section('▣', 'PRODUCTS'))
    print(leader("Unique Barcodes",        f"{total_barcodes:,}"))
    print(leader("Total Products",         f"{total_products:,}"))
    print(leader("Avg Products / Barcode", f"{avg_per_bc:.2f}"))
    print(leader("Barcodes w/ Multiples",  f"{barcodes_multi:,}"))
    if max_bc:
        print(leader("Largest Group", f"{max_bc[1]} products  (bc: {max_bc[0]})"))
    print()

    print(section('◈', 'IMAGES'))
    if total_products:
        pct_with = (products_with_image / total_products) * 100
        pct_wo   = 100 - pct_with
        wcol = C.GR if pct_with >= 50 else C.YE
        ocol = C.RE if pct_wo  >= 50 else C.YE
        print(leader("With Image URL",    f"{products_with_image:,}  ({pct_with:.1f}%)", wcol))
        print(leader("Without Image URL", f"{products_without_image:,}  ({pct_wo:.1f}%)", ocol))
    else:
        print(leader("With Image URL",    "0  (0.0%)", C.GY))
        print(leader("Without Image URL", "0  (0.0%)", C.GY))
    print()

    print(section('▤', 'STORAGE'))
    print(leader("Data Directory", f"{DATA_DIR}/"))
    print(leader("Total Size",     _human(total_size)))
    print(leader("index.json",     _human(index_size)))
    print(leader("api_keys.json",  _human(keys_size)))
    print(leader("Total Shards",   f"{len(shard_files)}"))
    print()

    if shard_sizes:
        active_name = os.path.basename(db.active_shard) if db.active_shard else ""
        print(f"    {C.D}{'Shard File':<34}{'Size':>14}{C.R}")
        print(f"    {C.GY}{'─' * 48}{C.R}")
        for name, sz in shard_sizes:
            is_active = (name == active_name)
            col = C.YE if is_active else C.GY
            marker = f"  {C.YE}◀ active{C.R}" if is_active else ""
            print(f"    {col}{name:<34}{_human(sz):>14}{C.R}{marker}")
        print()

    print(section('◎', 'ACTIVE SHARD'))
    if db.active_shard:
        print(leader("File", os.path.basename(db.active_shard)))
        print(leader("Rows", f"{db.active_count:,} / {SHARD_LIMIT:,}"))
        fill_pct = (db.active_count / SHARD_LIMIT) * 100 if SHARD_LIMIT else 0
        bar_len  = 29
        filled   = int(bar_len * min(db.active_count, SHARD_LIMIT) / SHARD_LIMIT) if SHARD_LIMIT else 0
        bcol = C.GR if fill_pct < 70 else (C.YE if fill_pct < 90 else C.RE)
        bar = f"{bcol}{'█' * filled}{C.GY}{'░' * (bar_len - filled)}{C.R}"
        print(leader("Fill",      f"[{bar}] {fill_pct:5.1f}%", C.R))
        print(leader("Remaining", f"{max(0, SHARD_LIMIT - db.active_count):,} rows", C.GY))
    print()

    print(section('✦', 'API KEYS'))
    dcol = C.GR if disabled_keys == 0 else C.YE
    print(leader("Total Keys", f"{total_keys}"))
    print(leader("Enabled",    f"{enabled_keys}", C.GR))
    print(leader("Disabled",   f"{disabled_keys}", dcol))
    print()

def manage_keys():
    if len(sys.argv) < 2:
        print("Key Management Commands:")
        print("  --add-key <key> --name <name> [--limits lookup:200,image:5,add:5]")
        print("  --remove-key <key>")
        print("  --list-keys")
        return

    if sys.argv[1] == '--add-key':
        try:
            key_idx = sys.argv.index('--add-key') + 1
            key = sys.argv[key_idx]
            name_idx = sys.argv.index('--name') + 1
            name = sys.argv[name_idx]
        except (ValueError, IndexError):
            print("Error: Invalid format. Use --add-key <key> --name <name>")
            return
        limits = {}
        if '--limits' in sys.argv:
            try:
                lim_idx = sys.argv.index('--limits') + 1
                lim_str = sys.argv[lim_idx]
                for part in lim_str.split(','):
                    k, v = part.split(':')
                    limits[k] = int(v)
            except (ValueError, IndexError):
                print("Warning: Invalid limits format. Ignoring.")
        success, msg = add_new_api_key(key, name, limits)
        print(f"{'✅' if success else '❌'} {msg}")

    elif sys.argv[1] == '--remove-key':
        if len(sys.argv) < 3:
            print("Error: Usage --remove-key <key>")
            return
        key = sys.argv[2]
        success, msg = remove_api_key(key)
        print(f"{'✅' if success else '❌'} {msg}")

    elif sys.argv[1] == '--list-keys':
        keys = load_api_keys()
        print("\n📋 Registered API Keys:")
        for k, v in keys.items():
            status = "✅ Active" if v.get('enabled', True) else "❌ Disabled"
            print(f"  - {k[:20]}... ({v.get('name')}) -> {status} | Limits: {v.get('limits', {})}")

# ==================== MAIN ====================
if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] in ['--add-key', '--remove-key', '--list-keys']:
            manage_keys()
        elif sys.argv[1] == '--add':
            interactive_add()
        elif sys.argv[1] == '--edit':
            interactive_edit()
        elif sys.argv[1] == '--list':
            list_all_products()
        elif sys.argv[1] == '--stats':
            show_stats()
        else:
            print("Unknown command. Available: --add, --edit, --list, --stats, --add-key, --remove-key, --list-keys")
    else:
        print(f"🚀 Multi-Product Barcode Server with Edit/Delete support running at: http://localhost:5000")
        print(f"🔑 Use 'X-API-Key' header for secure endpoints.")
        print(f"📊 Manage keys via CLI: --add-key, --remove-key, --list-keys")
        print(f"📝 Edit product: python barcode_server.py --edit")
        print(f"📋 List all products: python barcode_server.py --list")
        app.run(host='0.0.0.0', port=5000, debug=False)