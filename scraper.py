"""
Scraper coteetsport.ma — version "interception réseau".

Stratégie :
  Le site est une SPA React (root #root-betting) qui appelle en JSON
  l'API interne hébergée sur https://betting.sjmtech.ma. On laisse Chrome
  charger la page normalement (avec contournement Akamai via undetected-chromedriver
  + résolution reCAPTCHA via 2captcha si besoin) puis on intercepte les
  requêtes XHR/Fetch via le Chrome DevTools Protocol exposé par Selenium 4.
  On parse ensuite chaque réponse JSON pour en extraire les matchs/cotes.

Avantage : pas besoin de connaître les sélecteurs CSS ni les noms exacts
de l'API — on découvre tout à l'exécution.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import List, Dict, Any
from datetime import datetime, timezone

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from browser import get_driver
from captcha import solve_recaptcha_if_present

TARGET_URL = os.getenv("TARGET_URL", "https://www.coteetsport.ma/cote-sport")

# Mots-clés qu'on cherche dans l'URL des XHR pour repérer les endpoints "matchs"
MATCH_URL_HINTS = ("event", "match", "fixture", "sport", "betting", "odds")
# Domaine API interne du provider (Sisal / SJM Tech)
API_DOMAIN = "sjmtech.ma"


def _country_to_flag(name: str) -> str:
    table = {
        "maroc": "🇲🇦", "morocco": "🇲🇦",
        "france": "🇫🇷",
        "angleterre": "🇬🇧", "england": "🇬🇧",
        "espagne": "🇪🇸", "spain": "🇪🇸",
        "italie": "🇮🇹", "italy": "🇮🇹",
        "allemagne": "🇩🇪", "germany": "🇩🇪",
        "portugal": "🇵🇹",
        "belgique": "🇧🇪", "belgium": "🇧🇪",
        "pays-bas": "🇳🇱", "netherlands": "🇳🇱",
        "brésil": "🇧🇷", "bresil": "🇧🇷", "brazil": "🇧🇷",
        "argentine": "🇦🇷", "argentina": "🇦🇷",
        "international": "🌍", "europe": "🇪🇺", "monde": "🌍", "world": "🌍",
    }
    return table.get((name or "").strip().lower(), "⚽")


def _parse_iso(value: Any) -> str:
    """Normalise une date en ISO8601 UTC."""
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        # Timestamp en secondes ou millisecondes
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    s = str(value)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _walk(node: Any):
    """Parcours récursif d'un JSON arbitraire (yield chaque dict)."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _extract_matches_from_json(payload: Any) -> List[Dict]:
    """
    Heuristique tolérante : on cherche tout dict qui ressemble à un événement
    sportif (deux équipes + cotes 1/X/2). On ne fait AUCUNE supposition sur
    le nom exact des clés — on essaie plusieurs variantes courantes.
    """
    results: List[Dict] = []
    seen_ids = set()

    # Clés candidates pour chaque champ
    K_HOME = ("home", "homeTeam", "team1", "participant1", "competitor1", "homeName")
    K_AWAY = ("away", "awayTeam", "team2", "participant2", "competitor2", "awayName")
    K_LEAGUE = ("league", "tournament", "competition", "leagueName", "tournamentName")
    K_COUNTRY = ("country", "countryName", "category", "categoryName", "region")
    K_KICKOFF = ("startTime", "startDate", "kickoff", "date", "scheduled", "eventDate", "matchDate")
    K_ID = ("id", "eventId", "matchId", "eventCode")

    def first(d: Dict, keys, default=None):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return default

    def to_str(x):
        if isinstance(x, dict):
            return first(x, ("name", "shortName", "title", "label"), "")
        return str(x or "").strip()

    for d in _walk(payload):
        home = to_str(first(d, K_HOME))
        away = to_str(first(d, K_AWAY))
        if not home or not away or home == away:
            continue

        # Cherche les cotes 1/X/2 dans ce dict (ou un sous-dict markets/odds)
        odds_1 = odds_x = odds_2 = None
        sid_1 = sid_x = sid_2 = None

        for sub in _walk(d):
            # Format A : {"selection":"1"|"X"|"2", "odd":1.85, "id":"..."}
            sel = str(sub.get("selection") or sub.get("name") or sub.get("type") or sub.get("outcome") or "").strip().upper()
            val = sub.get("odd") or sub.get("price") or sub.get("value") or sub.get("decimal")
            sid = sub.get("id") or sub.get("selectionId") or sub.get("outcomeId")
            try:
                val_f = float(str(val).replace(",", ".")) if val is not None else None
            except Exception:
                val_f = None

            if val_f and sid is not None:
                if sel in ("1", "HOME", "1X2_1") and odds_1 is None:
                    odds_1, sid_1 = val_f, str(sid)
                elif sel in ("X", "DRAW", "1X2_X") and odds_x is None:
                    odds_x, sid_x = val_f, str(sid)
                elif sel in ("2", "AWAY", "1X2_2") and odds_2 is None:
                    odds_2, sid_2 = val_f, str(sid)

        if not (odds_1 and odds_x and odds_2):
            continue

        match_id = str(first(d, K_ID, f"{home}-{away}"))
        if match_id in seen_ids:
            continue
        seen_ids.add(match_id)

        country = to_str(first(d, K_COUNTRY, "International")) or "International"
        league = to_str(first(d, K_LEAGUE, "Football")) or "Football"
        kickoff = _parse_iso(first(d, K_KICKOFF))

        results.append({
            "id": match_id,
            "country": country,
            "flag": _country_to_flag(country),
            "league": league,
            "kickoff": kickoff,
            "home": home,
            "away": away,
            "odds": {
                "home": {"id": sid_1, "value": odds_1},
                "draw": {"id": sid_x, "value": odds_x},
                "away": {"id": sid_2, "value": odds_2},
            },
        })

    return results


def _capture_xhr_responses(driver, timeout: int = 25) -> List[Any]:
    """
    Active le CDP Network domain et collecte les réponses JSON
    venant de l'API du provider pendant 'timeout' secondes.
    """
    driver.execute_cdp_cmd("Network.enable", {})
    captured_bodies: List[Any] = []
    request_ids: List[str] = []

    # Selenium 4 expose les events CDP via get_log mais c'est limité.
    # On utilise plutôt une boucle qui interroge Network.getResponseBody
    # pour chaque request_id observé via les performance logs.
    end = time.time() + timeout
    seen_ids = set()
    while time.time() < end:
        try:
            logs = driver.get_log("performance")
        except Exception:
            time.sleep(0.5)
            continue

        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
            except Exception:
                continue
            if msg.get("method") != "Network.responseReceived":
                continue
            params = msg.get("params", {})
            response = params.get("response", {})
            url = response.get("url", "")
            mime = response.get("mimeType", "")
            if API_DOMAIN not in url:
                continue
            if "json" not in mime:
                continue
            if not any(h in url.lower() for h in MATCH_URL_HINTS):
                continue
            req_id = params.get("requestId")
            if not req_id or req_id in seen_ids:
                continue
            seen_ids.add(req_id)
            try:
                body = driver.execute_cdp_cmd(
                    "Network.getResponseBody", {"requestId": req_id}
                )
                raw = body.get("body", "")
                if body.get("base64Encoded"):
                    import base64
                    raw = base64.b64decode(raw).decode("utf-8", errors="ignore")
                captured_bodies.append(json.loads(raw))
                print(f"[scraper] capturé {len(raw)} bytes depuis {url[:80]}")
            except Exception as e:
                print(f"[scraper] erreur récup body {req_id}: {e}")
        time.sleep(0.8)

    return captured_bodies


def scrape_matches() -> List[Dict]:
    driver = get_driver()
    try:
        print(f"[scraper] ouverture {TARGET_URL}")
        driver.get(TARGET_URL)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        solve_recaptcha_if_present(driver)

        # On attend que le root SPA soit présent
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "root-betting"))
            )
        except Exception:
            print("[scraper] #root-betting absent, on continue quand même")

        # Léger scroll pour déclencher le lazy-load
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(0.6)

        # On capture pendant 25s les réponses JSON des XHR vers l'API
        payloads = _capture_xhr_responses(driver, timeout=25)
        print(f"[scraper] {len(payloads)} payloads capturés")

        all_matches: List[Dict] = []
        for p in payloads:
            all_matches.extend(_extract_matches_from_json(p))

        # Dédoublonnage final
        unique = {}
        for m in all_matches:
            unique[m["id"]] = m
        result = list(unique.values())
        print(f"[scraper] {len(result)} matchs uniques retournés")
        return result
    finally:
        try:
            driver.quit()
        except Exception:
            pass
