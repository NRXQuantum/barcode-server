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
from flask import Flask, request, jsonify, send_file, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from concurrent.futures import ThreadPoolExecutor

# ==================== CONFIGURATION ====================
DATA_DIR = "barcode_data"
INDEX_FILE = os.path.join(DATA_DIR, "index.json")
API_KEYS_FILE = os.path.join(DATA_DIR, "api_keys.json")
SHARD_LIMIT = 10000
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== API KEYS MANAGER (unchanged) ====================
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
        with open(API_KEYS_FILE, 'w') as f:
            json.dump(default_data, f, indent=2)
        logger.info(f"Default API key created: {default_key}")
        return default_data
    with open(API_KEYS_FILE, 'r') as f:
        return json.load(f)

def save_api_keys(keys_data):
    with open(API_KEYS_FILE, 'w') as f:
        json.dump(keys_data, f, indent=2)

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

# ==================== MONITORING METRICS ====================
metrics = {
    'total_requests': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'avg_response_time': 0,
    'request_times': []
}

def update_metrics(start_time, cache_hit=False):
    elapsed = (time.time() - start_time) * 1000
    metrics['total_requests'] += 1
    if cache_hit:
        metrics['cache_hits'] += 1
    else:
        metrics['cache_misses'] += 1
    metrics['request_times'].append(elapsed)
    if len(metrics['request_times']) > 1000:
        metrics['request_times'].pop(0)
    metrics['avg_response_time'] = sum(metrics['request_times']) / len(metrics['request_times'])

# ==================== SECURITY HELPERS (unchanged) ====================
def sanitize_csv_field(value):
    if isinstance(value, str) and value and value[0] in '+-=@':
        return "'" + value
    return value

def is_safe_url(url):
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False, "Only HTTP/HTTPS protocols are allowed."
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid hostname."
        try:
            ip_addresses = socket.getaddrinfo(hostname, None)
        except:
            return False, "Cannot resolve hostname."
        for addr in ip_addresses:
            ip_str = addr[4][0]
            if ':' in ip_str:
                continue
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_multicast or ip_obj.is_link_local:
                    return False, f"Private/Internal IP address not allowed: {ip_str}"
                if ip_str.startswith('169.254.'):
                    return False, f"Link-local IP blocked: {ip_str}"
            except:
                return False, "Invalid IP address format."
        return True, None
    except Exception as e:
        return False, f"Security check failed: {str(e)}"

def validate_image_url(url, timeout=5):
    if not url:
        return False, "URL is empty."
    safe, msg = is_safe_url(url)
    if not safe:
        return False, f"Security validation failed: {msg}"
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=False)
        if resp.status_code not in (200, 301, 302):
            return False, f"HTTP error: {resp.status_code}"
        content_type = resp.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            return False, f"Invalid content type: {content_type}. Only images are allowed."
        content_length = resp.headers.get('content-length')
        if content_length and int(content_length) > MAX_IMAGE_SIZE:
            return False, f"Image exceeds maximum size limit ({MAX_IMAGE_SIZE} bytes)."
        return True, None
    except requests.exceptions.Timeout:
        return False, "Request timeout."
    except requests.exceptions.ConnectionError:
        return False, "Connection failed."
    except Exception as e:
        return False, f"Validation error: {str(e)}"

def download_safe_image(url):
    safe, msg = is_safe_url(url)
    if not safe:
        raise ValueError(f"URL blocked: {msg}")
    resp = requests.get(url, timeout=10, stream=True, allow_redirects=False)
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

# ==================== DATABASE CLASS (MULTI-PRODUCT PER BARCODE) ====================
class BarcodeDB:
    def __init__(self):
        self.index = {}  # barcode -> list of product dicts
        self.active_shard = None
        self.active_count = 0
        self.lock = threading.Lock()
        self._initialize()

    def _initialize(self):
        # ----- Migrate legacy single CSV if exists -----
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
                        # Build index: group by barcode
                        bc = row['barcode']
                        if bc not in self.index:
                            self.index[bc] = []
                        self.index[bc].append({
                            'name': row['product_name'],
                            'image': row['image_url'],
                            'shard': os.path.basename(shard_name)
                        })
                with open(INDEX_FILE, 'w') as f:
                    json.dump(self.index, f, indent=2)
                logger.info(f"Migration complete. {len(rows)} entries moved.")

        # ----- Load existing index (may be old dict format) -----
        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, 'r') as f:
                data = json.load(f)
            # Convert old format (barcode -> dict) to new format (barcode -> list)
            if data and isinstance(next(iter(data.values())), dict):
                logger.info("Converting old index format to multi-product format...")
                new_index = {}
                for bc, prod in data.items():
                    # prod was a dict with 'name', 'image', 'shard'
                    new_index[bc] = [prod]
                self.index = new_index
                # Save new format
                with open(INDEX_FILE, 'w') as f:
                    json.dump(self.index, f, indent=2)
                logger.info("Conversion complete.")
            else:
                self.index = data

        # ----- Manage shard files -----
        shard_files = glob.glob(os.path.join(DATA_DIR, "my_products_*.csv"))
        if not shard_files:
            self._create_new_shard()
        else:
            shard_files.sort(key=lambda x: int(x.split('_')[-1].split('.')[0]))
            self.active_shard = shard_files[-1]
            with open(self.active_shard, 'r', encoding='utf-8') as f:
                self.active_count = sum(1 for _ in f) - 1
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
        urls = re.findall(r'https?://[^\s"\']+', text)
        return urls[0] if urls else text.strip()

    def _cache_image_async(self, img_url, barcode):
        try:
            content, content_type = download_safe_image(img_url)
            cache.set(f"img_{barcode}", (content, content_type), timeout=86400)
            logger.info(f"Background cache ready for {barcode}")
        except Exception as e:
            logger.warning(f"Background caching failed for {barcode}: {e}")

    # ---------- ADD: allows multiple products per barcode, but prevents exact duplicate (same barcode+name) ----------
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
            # Check for exact duplicate (same barcode and same name)
            if raw_barcode in self.index:
                for prod in self.index[raw_barcode]:
                    if prod['name'] == safe_name:
                        return False, f"Product with barcode '{raw_barcode}' and name '{safe_name}' already exists."

            # If barcode not present, create new list
            if raw_barcode not in self.index:
                self.index[raw_barcode] = []

            # Append new product
            new_product = {
                'name': safe_name,
                'image': clean_img,
                'shard': os.path.basename(self.active_shard)
            }
            self.index[raw_barcode].append(new_product)

            # Write to CSV (each product as separate row)
            if self.active_count >= SHARD_LIMIT:
                self._create_new_shard()
            with open(self.active_shard, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([safe_barcode, safe_name, clean_img])
            self.active_count += 1

            # Save index
            with open(INDEX_FILE, 'w') as f:
                json.dump(self.index, f, indent=2)

            # Async image cache
            if clean_img:
                executor.submit(self._cache_image_async, clean_img, raw_barcode)

            logger.info(f"Product added: {raw_barcode} -> {safe_name}")
            return True, "OK"

    # ---------- LOOKUP: returns list of products for a barcode ----------
    def lookup(self, barcode):
        raw = barcode.strip()
        return self.index.get(raw, [])

    # ---------- GET ALL: flatten all products into list of dicts ----------
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

# ==================== FLASK ROUTES ====================
@app.route('/api/')
@limiter.limit("30 per second")
def api_home():
    return jsonify({
        "message": "Multi-Product Barcode API (same barcode supports multiple products)",
        "auth": "Provide X-API-Key header for POST/Export endpoints.",
        "endpoints": {
            "GET /api/lookup/<barcode>": "Public (returns list of products)",
            "GET /api/lookup/<barcode>/image": "Public (downloads first product's image)",
            "POST /api/add": "🔒 Requires Key (async background cache)",
            "GET /api/all": "Public (rate limited)",
            "GET /api/export": "🔒 Requires Key (ZIP download)",
            "GET /api/metrics": "Public (server performance)"
        }
    })

@app.route('/api/add', methods=['POST'])
@limiter.limit("5 per second", key_func=get_custom_key)
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

@app.route('/api/lookup/<barcode>')
@limiter.limit(get_lookup_limit, key_func=get_custom_key)
def api_lookup_product(barcode):
    start = time.time()
    # Check cache for this barcode (store list in cache)
    cached = cache.get(barcode)
    if cached is not None:
        update_metrics(start, cache_hit=True)
        # cached is the list of products
        return jsonify({
            "barcode": barcode,
            "products": cached
        })

    products = db.lookup(barcode)
    if products:
        # Cache the list (products is list of dicts)
        cache.set(barcode, products, timeout=3600)
        update_metrics(start, cache_hit=False)
        return jsonify({
            "barcode": barcode,
            "products": products
        })
    update_metrics(start)
    return jsonify({"error": "Barcode not found."}), 404

@app.route('/api/lookup/<barcode>/image')
@limiter.limit(get_image_limit, key_func=get_custom_key)
def api_download_image(barcode):
    start = time.time()
    products = db.lookup(barcode)
    if not products:
        return jsonify({"error": "Barcode not found."}), 404
    # Use the first product's image (you may want to handle multiple images)
    first = products[0]
    img_url = first.get('image', '')
    if not img_url:
        return jsonify({"error": "No image associated with this product."}), 404

    cached_img = cache.get(f"img_{barcode}")
    if cached_img:
        content, content_type = cached_img
        update_metrics(start, cache_hit=True)
        return send_file(
            io.BytesIO(content),
            mimetype=content_type,
            as_attachment=True,
            download_name=f"{barcode}.jpg"
        )

    try:
        content, content_type = download_safe_image(img_url)
        cache.set(f"img_{barcode}", (content, content_type), timeout=86400)
        update_metrics(start, cache_hit=False)
        return send_file(
            io.BytesIO(content),
            mimetype=content_type,
            as_attachment=True,
            download_name=f"{barcode}.jpg"
        )
    except Exception as e:
        logger.error(f"Image download failed: {e}")
        return jsonify({"error": f"Failed to download image: {str(e)}"}), 500

@app.route('/api/all')
@limiter.limit("30 per second")
def api_all_products():
    start = time.time()
    data = db.get_all()
    update_metrics(start)
    return jsonify(data)

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

@app.route('/api/metrics')
@limiter.limit("10 per minute")
def get_metrics():
    return jsonify({
        "total_requests": metrics['total_requests'],
        "cache_hits": metrics['cache_hits'],
        "cache_misses": metrics['cache_misses'],
        "cache_hit_ratio": round(metrics['cache_hits'] / max(1, metrics['total_requests']) * 100, 2),
        "avg_response_time_ms": round(metrics['avg_response_time'], 2),
        "active_shard": os.path.basename(db.active_shard),
        "total_entries": len(db.index)  # number of unique barcodes
    })

# ==================== REDIRECTS ====================
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
    shards = glob.glob(os.path.join(DATA_DIR, "my_products_*.csv"))
    total_products = 0
    for prod_list in db.index.values():
        total_products += len(prod_list)
    print(f"\n📊 Unique Barcodes: {len(db.index)}")
    print(f"📦 Total Products: {total_products}")
    print(f"📁 Total Shards: {len(shards)}")
    print(f"📄 Active Shard: {os.path.basename(db.active_shard)} ({db.active_count} rows)")

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
            except:
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
        elif sys.argv[1] == '--stats':
            show_stats()
        else:
            print("Unknown command. Available: --add, --stats, --add-key, --remove-key, --list-keys")
    else:
        print(f"🚀 Multi-Product Barcode Server running at: http://localhost:5000")
        print(f"🔑 Use 'X-API-Key' header for secure endpoints.")
        print(f"📊 Manage keys via CLI: --add-key, --remove-key, --list-keys")
        app.run(host='0.0.0.0', port=5000, debug=False)