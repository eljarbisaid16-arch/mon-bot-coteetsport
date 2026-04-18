"""
Crée un Chrome headless prêt à fonctionner sur Railway,
avec un user-agent réaliste pour éviter la détection bot basique.
"""
import os
import undetected_chromedriver as uc

CHROME_BIN = os.getenv("GOOGLE_CHROME_BIN", "/usr/bin/google-chrome")


def get_driver():
    options = uc.ChromeOptions()
    options.binary_location = CHROME_BIN
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--lang=fr-FR")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    driver = uc.Chrome(options=options, version_main=None)
    driver.set_page_load_timeout(60)
    return driver
