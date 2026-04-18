"""
Résolution reCAPTCHA via 2captcha.
Variable d'env requise : CAPTCHA_API_KEY
"""
import os
import time
from selenium.webdriver.common.by import By
from twocaptcha import TwoCaptcha

CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY", "")
solver = TwoCaptcha(CAPTCHA_API_KEY) if CAPTCHA_API_KEY else None


def solve_recaptcha_if_present(driver):
    """Détecte un reCAPTCHA v2/v3 et le résout via 2captcha si présent."""
    if not solver:
        return
    try:
        sitekey_el = driver.find_element(
            By.CSS_SELECTOR, "[data-sitekey], .g-recaptcha[data-sitekey]"
        )
    except Exception:
        return  # pas de captcha visible

    sitekey = sitekey_el.get_attribute("data-sitekey")
    if not sitekey:
        return

    print(f"[captcha] reCAPTCHA détecté sitekey={sitekey}, résolution via 2captcha…")
    result = solver.recaptcha(sitekey=sitekey, url=driver.current_url)
    token = result["code"]

    # Injecter le token dans la page
    driver.execute_script(
        "document.getElementById('g-recaptcha-response').style.display = 'block';"
        "document.getElementById('g-recaptcha-response').value = arguments[0];",
        token,
    )
    # Si la page utilise un callback, le déclencher
    driver.execute_script(
        "if (typeof onCaptchaSuccess === 'function') onCaptchaSuccess(arguments[0]);",
        token,
    )
    time.sleep(1)
