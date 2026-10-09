"""Lookup prodotto da codice a barre via Open Food Facts (API aperta, gratuita).

Dato un EAN/UPC ritorna nome, marca, quantità confezione e i valori nutrizionali
per 100 g (kcal/proteine/carboidrati/grassi) + ingredienti, così la dispensa di
planmydinner si può popolare con la fotocamera (stile Yuka). Nessuna chiave.
"""
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)

_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
_FIELDS = ("product_name,product_name_it,brands,quantity,nutriments,"
           "image_front_small_url,ingredients_text_it,ingredients_text,categories_tags")
# Open Food Facts chiede uno User-Agent identificativo.
_UA = "planmydinner/1.0 (self-hosted meal planner)"


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return round(f, 1) if f == f else None
    except (TypeError, ValueError):
        return None


def lookup_barcode(code: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
    """Ritorna {found, barcode, name, brands, quantity_text, nutrition(per100g),
    image_url, ingredients} o {'found': False} se il prodotto non esiste.
    None solo se la chiamata fallisce del tutto."""
    code = (code or "").strip()
    if not code.isdigit() or not (6 <= len(code) <= 14):
        return {"found": False, "barcode": code, "detail": "Codice non valido"}
    url = _OFF_URL.format(code=urllib.parse.quote(code)) + "?fields=" + urllib.parse.quote(_FIELDS)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _LOGGER.warning("Open Food Facts lookup fallito per %s: %s", code, e)
        return None
    if data.get("status") != 1 or not data.get("product"):
        return {"found": False, "barcode": code}
    p = data["product"]
    nut = p.get("nutriments") or {}
    nutrition = {
        "kcal": _num(nut.get("energy-kcal_100g")),
        "protein_g": _num(nut.get("proteins_100g")),
        "carbs_g": _num(nut.get("carbohydrates_100g")),
        "fat_g": _num(nut.get("fat_100g")),
    }
    name = (p.get("product_name_it") or p.get("product_name") or "").strip()
    return {
        "found": True,
        "barcode": code,
        "name": name,
        "brands": (p.get("brands") or "").strip(),
        "quantity_text": (p.get("quantity") or "").strip(),
        "nutrition": nutrition if any(v is not None for v in nutrition.values()) else None,
        "image_url": p.get("image_front_small_url"),
        "ingredients": (p.get("ingredients_text_it") or p.get("ingredients_text") or "").strip(),
    }
