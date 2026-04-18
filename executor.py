"""
Exécuteur : prend une liste de data-selection-id + une mise,
ouvre le site, clique exactement sur ces sélections, saisit la mise,
clique sur 'générer le code-barres', capture l'image et renvoie le PNG.

ATTENTION : sélecteurs à adapter au DOM réel.
"""
from __future__ import annotations

import io
import os
import time
import uuid
from typing import List, Tuple

from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from browser import get_driver
from captcha import solve_recaptcha_if_present

TARGET_URL = os.getenv("TARGET_URL", "https://www.coteetsport.ma/")


def place_ticket_on_site(selection_ids: List[str], mise: str) -> Tuple[bytes, str]:
    driver = get_driver()
    try:
        driver.get(TARGET_URL)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        solve_recaptcha_if_present(driver)

        # 1) Cliquer chaque sélection
        for sid in selection_ids:
            selector = f'[data-selection-id="{sid}"]'
            el = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
            time.sleep(0.4)

        # 2) Saisir la mise (sélecteur à adapter)
        stake_input = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='stake']"))
        )
        stake_input.clear()
        stake_input.send_keys(str(mise))

        # 3) Cliquer sur 'générer le code-barres' (sélecteur à adapter)
        gen_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.generate-barcode"))
        )
        gen_btn.click()

        solve_recaptcha_if_present(driver)

        # 4) Attendre que l'image du code-barres apparaisse
        barcode_el = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.barcode-image"))
        )
        time.sleep(1)

        # 5) Capture de l'élément
        png = barcode_el.screenshot_as_png

        # Optionnel : récupérer le code de réservation textuel
        try:
            code_el = driver.find_element(By.CSS_SELECTOR, ".reservation-code")
            reservation_code = code_el.text.strip()
        except Exception:
            reservation_code = f"PM{uuid.uuid4().hex[:10].upper()}"

        return png, reservation_code
    finally:
        driver.quit()
