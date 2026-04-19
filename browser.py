"""
Crée un Chrome headless prêt à fonctionner sur Railway,
avec un user-agent réaliste, "performance logs" CDP activés,
et support optionnel d'un proxy résidentiel (HTTP ou SOCKS5)
avec authentification user:pass — indispensable pour contourner
le blocage Akamai/datacenter de coteetsport.ma.

Variables d'environnement (toutes optionnelles, à définir sur Railway) :
  PROXY_HOST     ex: brd.superproxy.io
  PROXY_PORT     ex: 22225
  PROXY_USER     ex: brd-customer-xxx-zone-residential-country-ma
  PROXY_PASS     ex: votre_password
  PROXY_SCHEME   http (défaut) ou socks5
"""
import os
import shutil
import tempfile
import zipfile

import undetected_chromedriver as uc
from selenium.webdriver import DesiredCapabilities

CHROME_BIN = os.getenv("GOOGLE_CHROME_BIN", "/usr/bin/google-chrome")

PROXY_HOST = os.getenv("PROXY_HOST", "").strip()
PROXY_PORT = os.getenv("PROXY_PORT", "").strip()
PROXY_USER = os.getenv("PROXY_USER", "").strip()
PROXY_PASS = os.getenv("PROXY_PASS", "").strip()
PROXY_SCHEME = (os.getenv("PROXY_SCHEME", "http").strip() or "http").lower()


def _build_proxy_auth_extension() -> str:
    """Construit une extension Chrome (.zip) injectant les credentials du proxy.
    Chrome n'accepte pas user:pass@host dans --proxy-server, il faut une extension."""
    manifest = {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Proxy Auth",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking",
        ],
        "background": {"scripts": ["background.js"]},
        "minimum_chrome_version": "22.0.0",
    }
    background_js = (
        "var config = {\n"
        "  mode: 'fixed_servers',\n"
        "  rules: {\n"
        "    singleProxy: { scheme: '%s', host: '%s', port: parseInt(%s) },\n"
        "    bypassList: ['localhost']\n"
        "  }\n"
        "};\n"
        "chrome.proxy.settings.set({ value: config, scope: 'regular' }, function() {});\n"
        "function callbackFn(details) {\n"
        "  return { authCredentials: { username: '%s', password: '%s' } };\n"
        "}\n"
        "chrome.webRequest.onAuthRequired.addListener(\n"
        "  callbackFn, { urls: ['<all_urls>'] }, ['blocking']\n"
        ");\n"
    ) % (PROXY_SCHEME, PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS)

    import json as _json
    tmp_dir = tempfile.mkdtemp(prefix="proxy_ext_")
    zip_path = os.path.join(tmp_dir, "proxy_auth.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", _json.dumps(manifest))
        zf.writestr("background.js", background_js)
    return zip_path


def get_driver():
    options = uc.ChromeOptions()
    options.binary_location = CHROME_BIN
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--lang=fr-FR,fr;q=0.9")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Proxy résidentiel (recommandé : géolocalisation Maroc)
    if PROXY_HOST and PROXY_PORT:
        if PROXY_USER and PROXY_PASS:
            try:
                ext_path = _build_proxy_auth_extension()
                options.add_extension(ext_path)
                print(f"[browser] proxy {PROXY_SCHEME}://{PROXY_HOST}:{PROXY_PORT} (auth via extension)")
            except Exception as e:
                print(f"[browser] erreur extension proxy: {e}, fallback --proxy-server")
                options.add_argument(f"--proxy-server={PROXY_SCHEME}://{PROXY_HOST}:{PROXY_PORT}")
        else:
            options.add_argument(f"--proxy-server={PROXY_SCHEME}://{PROXY_HOST}:{PROXY_PORT}")
            print(f"[browser] proxy {PROXY_SCHEME}://{PROXY_HOST}:{PROXY_PORT} (sans auth)")
    else:
        print("[browser] AUCUN proxy configuré — risque de blocage Akamai")

    # Performance logs CDP (interception XHR)
    caps = DesiredCapabilities.CHROME.copy()
    caps["goog:loggingPrefs"] = {"performance": "ALL", "browser": "ALL"}

    driver = uc.Chrome(
        options=options,
        version_main=None,
        desired_capabilities=caps,
    )
    driver.set_page_load_timeout(90)
    return driver
