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
CAPTURE_TIMEOUT = int(os.getenv("CAPTURE_TIMEOUT", "40"))

# Cache du dernier debug (URLs + extraits de body) pour l'endpoint /debug/raw-xhr
_LAST_DEBUG: Dict[str, Any] = {"captured": [], "ran_at": 0}


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
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
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
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _extract_matches_from_json(payload: Any) -> List[Dict]:
    results: List[Dict] = []
    seen_ids = set()

    K_HOME = ("home", "homeTeam", "team1", "participant1", "competitor1", "homeName", "host")
    K_AWAY = ("away", "awayTeam", "team2", "participant2", "competitor2", "awayName", "guest")
    K_LEAGUE = ("league", "tournament", "competition", "leagueName", "tournamentName", "competitionName")
    K_COUNTRY = ("country", "countryName", "category", "categoryName", "region", "nation")
    K_KICKOFF = ("startTime", "startDate", "kickoff", "date", "scheduled", "eventDate", "matchDate", "dt")
    K_ID = ("id", "eventId", "matchId", "eventCode", "code")

    def first(d: Dict, keys, default=None):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return default

    def to_str(x):
        if isinstance(x, dict):
            return first(x, ("name", "shortName", "title", "label", "desc"), "")
        return str(x or "").strip()

    for d in _walk(payload):
        home = to_str(first(d, K_HOME))
        away = to_str(first(d, K_AWAY))
        if not home or not away or home == away:
            continue

        odds_1 = odds_x = odds_2 = None
        sid_1 = sid_x = sid_2 = None

        for sub in _walk(d):
            sel = str(sub.get("selection") or sub.get("name") or sub.get("type") or sub.get("outcome") or sub.get("sign") or "").strip().upper()
            val = sub.get("odd") or sub.get("price") or sub.get("value") or sub.get("decimal") or sub.get("quote")
            sid = sub.get("id") or sub.get("selectionId") or sub.get("outcomeId")
            try:
                val_f = float(str(val).replace(",", ".")) if val is not None else None
            except Exception:
                val_f = None

            if val_f and sid is not None:
                if sel in ("1", "HOME", "1X2_1") and odds_1 is None:
                    odds_1, sid_1 = val_f, str(sid)
                elif sel in ("X", "DRAW", "1X2_X", "N") and odds_x is None:
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


def _capture_all_xhr(driver, timeout: int) -> List[Dict[str, Any]]:
    """Capture TOUTES les réponses JSON (pas de filtre domaine ni mots-clés).
    Retourne une liste de dicts {url, mime, body_text, parsed_json_or_none}."""
    driver.execute_cdp_cmd("Network.enable", {})
    captured: List[Dict[str, Any]] = []
    seen_ids = set()
    end = time.time() + timeout

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
            mime = (response.get("mimeType") or "").lower()
            req_id = params.get("requestId")
            if not req_id or req_id in seen_ids:
                continue
            # On garde tout ce qui ressemble à du JSON
            if "json" not in mime and not url.endswith(".json"):
                continue
            seen_ids.add(req_id)
            try:
                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": req_id})
                raw = body.get("body", "")
                if body.get("base64Encoded"):
                    import base64 as _b64
                    raw = _b64.b64decode(raw).decode("utf-8", errors="ignore")
                parsed = None
                try:
                    parsed = json.loads(raw)
                except Exception:
                    pass
                captured.append({
                    "url": url,
                    "mime": mime,
                    "size": len(raw),
                    "body_preview": raw[:1500],
                    "parsed": parsed,
                })
                print(f"[scraper] XHR JSON {len(raw)}B {url[:100]}")
            except Exception as e:
                print(f"[scraper] body err {req_id}: {e}")
        time.sleep(0.8)

    return captured


def _open_and_capture(timeout: int = CAPTURE_TIMEOUT) -> List[Dict[str, Any]]:
    driver = get_driver()
    try:
        print(f"[scraper] ouverture {TARGET_URL}")
        driver.get(TARGET_URL)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        solve_recaptcha_if_present(driver)

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "root-betting"))
            )
        except Exception:
            print("[scraper] #root-betting absent, on continue")

        # Scroll pour déclencher lazy-load
        for _ in range(5):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(0.5)

        return _capture_all_xhr(driver, timeout=timeout)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def scrape_matches() -> List[Dict]:
    captured = _open_and_capture()
    # Mémoriser pour debug
    _LAST_DEBUG["captured"] = [
        {"url": c["url"], "mime": c["mime"], "size": c["size"], "body_preview": c["body_preview"]}
        for c in captured
    ]
    _LAST_DEBUG["ran_at"] = int(time.time())

    all_matches: List[Dict] = []
    for c in captured:
        if c.get("parsed") is not None:
            all_matches.extend(_extract_matches_from_json(c["parsed"]))

    unique = {}
    for m in all_matches:
        unique[m["id"]] = m
    result = list(unique.values())
    print(f"[scraper] {len(result)} matchs uniques retournés ({len(captured)} XHR JSON)")
    return result


def debug_capture() -> Dict[str, Any]:
    """Si aucune capture récente (>2 min), refait un cycle complet."""
    if not _LAST_DEBUG["captured"] or (time.time() - _LAST_DEBUG["ran_at"]) > 120:
        scrape_matches()
    return {
        "ran_at": _LAST_DEBUG["ran_at"],
        "xhr_count": len(_LAST_DEBUG["captured"]),
        "xhr": _LAST_DEBUG["captured"],
    }
