import os
import time
import threading
import requests
import logging
from barcode_server import app  # আপনার মূল ফাইল থেকে অ্যাপ ইমপোর্ট করুন

# ==================== CONFIGURATION ====================
# PING_URL = "https://barcode-server-am77.onrender.com"  # আপনি চাইলে আপনার URL বসান
PING_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://barcode-server-am77.onrender.com')
PING_INTERVAL = 12 * 60  # 12 মিনিট

# লগিং
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== পিঙ্গার ফাংশন (পেছনের থ্রেডে চলবে) ====================
def ping_loop():
    """প্রতি ১২ মিনিটে নিজের সার্ভারে রিকোয়েস্ট পাঠায় (যাতে Render বন্ধ না করে)।"""
    while True:
        try:
            # '/api/' এন্ডপয়েন্টে পিং পাঠাই (যা খুব দ্রুত সাড়া দেয়)
            response = requests.get(f"{PING_URL}/api/", timeout=10)
            if response.status_code == 200:
                logger.info(f"✅ Self-ping successful (Status: {response.status_code})")
            else:
                logger.warning(f"⚠️ Self-ping returned status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Self-ping failed: {e}")
        
        logger.info(f"😴 Pinger sleeping for {PING_INTERVAL // 60} minutes...")
        time.sleep(PING_INTERVAL)

# ==================== মেইন ====================
if __name__ == "__main__":
    # ১. পিঙ্গার থ্রেডটি ডেমন (Background) হিসেবে স্টার্ট করি
    pinger_thread = threading.Thread(target=ping_loop, daemon=True)
    pinger_thread.start()
    logger.info("🚀 Background pinger thread started.")

    # ২. মূল Flask অ্যাপটি রান করি (এটাই ফোরগ্রাউন্ডে থাকবে)
    port = int(os.environ.get("PORT", 5000))  # Render এর জন্য পোর্ট ভেরিয়েবল
    logger.info(f"🌐 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port)
