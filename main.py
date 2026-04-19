"""
PariMatchia bot — FastAPI service
Endpoints:
  GET  /health
  GET  /matches            -> liste des matchs scrapés depuis coteetsport.ma
  POST /place-ticket       -> { ids: string[], mise: string }
                              ouvre Chrome, clique sur les sélections, tape la mise,
                              clique sur 'générer le code-barres' et renvoie l'image base64.

Sécurité : protection par Bearer token via la variable d'env API_TOKEN.
Captcha   : résolution via 2captcha (variable d'env CAPTCHA_API_KEY).
"""
import base64
import os
import time
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scraper import scrape_matches, debug_capture, debug_screenshot
from executor import place_ticket_on_site

API_TOKEN = os.getenv("API_TOKEN", "")

app = FastAPI(title="PariMatchia Bot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(authorization: Optional[str] = Header(None)):
    if not API_TOKEN:
        return  # token non configuré -> ouvert (dev)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


class PlaceTicketBody(BaseModel):
    ids: List[str] = Field(..., description="Liste des data-selection-id, ex: ['1234_1','5678_X']")
    mise: str = Field(..., description="Montant de la mise, ex: '50'")


@app.get("/health")
def health():
    return {"status": "ok", "service": "parimatchia-bot"}


@app.get("/matches", dependencies=[Depends(require_token)])
def matches():
    data = scrape_matches()
    return {"matches": data, "count": len(data), "fetched_at": int(time.time())}


@app.get("/debug/raw-xhr", dependencies=[Depends(require_token)])
def debug_raw_xhr():
    """Retourne TOUTES les XHR JSON capturées (URL + 1500 premiers caractères du body).
    Sert à découvrir le vrai format de l'API du site pour adapter le parser."""
    return debug_capture()


@app.get("/debug/screenshot", dependencies=[Depends(require_token)])
def debug_screenshot_endpoint():
    """Renvoie une capture PNG (base64) de ce que Chrome headless voit sur TARGET_URL.
    Indispensable pour diagnostiquer un blocage Akamai/captcha/page blanche."""
    png = debug_screenshot()
    b64 = base64.b64encode(png).decode("ascii")
    return {"image": f"data:image/png;base64,{b64}", "size": len(png)}


@app.post("/place-ticket", dependencies=[Depends(require_token)])
def place_ticket(body: PlaceTicketBody):
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids vide")
    try:
        png_bytes, reservation_code = place_ticket_on_site(body.ids, body.mise)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Echec validation: {e}")

    b64 = base64.b64encode(png_bytes).decode("ascii")
    return {
        "reservation_code": reservation_code,
        "barcode_image": f"data:image/png;base64,{b64}",
    }
