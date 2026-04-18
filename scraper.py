"""
Scraper / mapper / crawler pour coteetsport.ma.

ATTENTION : ce code est un SQUELETTE. Les sélecteurs CSS (data-match,
data-selection-id, .league-name, etc.) doivent être ajustés à la
structure réelle du site, qui change régulièrement.
"""
from __future__ import annotations

import os
import time
from typing import List, Dict

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from browser import get_driver
from captcha import solve_recaptcha_if_present

TARGET_URL = os.getenv("TARGET_URL", "https://www.coteetsport.ma/")


def scrape_matches() -> List[Dict]:
    driver = get_driver()
    try:
        driver.get(TARGET_URL)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        solve_recaptcha_if_present(driver)
        time.sleep(2)

        # ===== À ADAPTER : sélecteurs réels du site =====
        match_nodes = driver.find_elements(By.CSS_SELECTOR, "[data-match]")
        results: List[Dict] = []

        for node in match_nodes:
            try:
                country = (node.get_attribute("data-country") or "International").strip()
                league = (node.get_attribute("data-league") or "Football").strip()
                home = node.find_element(By.CSS_SELECTOR, ".team-home").text.strip()
                away = node.find_element(By.CSS_SELECTOR, ".team-away").text.strip()
                kickoff = node.get_attribute("data-kickoff") or ""

                odd_nodes = node.find_elements(By.CSS_SELECTOR, "[data-selection-id]")
                odds = {"home": None, "draw": None, "away": None}
                # Convention : .pick-1 / .pick-X / .pick-2
                for o in odd_nodes:
                    sid = o.get_attribute("data-selection-id")
                    val = float(o.text.strip().replace(",", "."))
                    cls = o.get_attribute("class") or ""
                    if "pick-1" in cls:
                        odds["home"] = {"id": sid, "value": val}
                    elif "pick-X" in cls:
                        odds["draw"] = {"id": sid, "value": val}
                    elif "pick-2" in cls:
                        odds["away"] = {"id": sid, "value": val}

                if not all(odds.values()):
                    continue

                results.append({
                    "id": node.get_attribute("data-match"),
                    "country": country,
                    "flag": "",
                    "league": league,
                    "kickoff": kickoff,
                    "home": home,
                    "away": away,
                    "odds": odds,
                })
            except Exception:
                continue

        return results
    finally:
        driver.quit()
