"""Scontrini digitali Lidl Plus: token, elenco scontrini, articoli.

Client minimo scritto apposta invece di usare `lidlplus-api`: quella libreria
ha f-string valide solo da Python 3.12 (l'immagine Docker è 3.11) e si porta
dietro playwright, qrcode e jwkest per fare il login, che qui non serve: il
refresh token si ottiene una volta dal PC (vedi manual_auth.py) e poi basta.

Il refresh token RUOTA: ogni rinnovo ne restituisce uno nuovo e quello vecchio
smette di valere. Chi chiama `refresh_access_token` deve salvare subito quello
restituito, altrimenti la sincronizzazione funziona una volta sola.
"""
import base64
import html as _html
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

_TOKEN_URL = "https://accounts.lidl.com/connect/token"
_TICKETS_URL = "https://tickets.lidlplus.com/api/v2/{country}/tickets"
_TICKET_URL = "https://tickets.lidlplus.com/api/v3/{country}/tickets/{ticket_id}"
_CLIENT_SECRET = base64.b64encode(b"LidlPlusNativeClient:secret").decode()
_APP_HEADERS = {
    "App-Version": "16.43.4",
    "Operating-System": "Android",
    "App": "com.lidl.eci.lidlplus",
    "User-Agent": "okhttp/5.3.2",
    "OS-Version": "16",
}


class LidlError(Exception):
    """Errore parlante per l'utente (token scaduto, servizio giù...)."""


class LidlAuthError(LidlError):
    """Il refresh token non vale più: va rifatto il collegamento."""


def refresh_access_token(refresh_token: str, timeout: float = 15) -> Tuple[str, str]:
    """(access_token, nuovo_refresh_token). Il nuovo va salvato SUBITO."""
    try:
        res = httpx.post(
            _TOKEN_URL,
            headers={"Authorization": f"Basic {_CLIENT_SECRET}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"refresh_token": refresh_token, "grant_type": "refresh_token"},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise LidlError(f"Lidl Plus non raggiungibile: {e}") from e
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code in (400, 401) or "access_token" not in body:
        # invalid_grant = token già usato altrove, revocato o scaduto
        raise LidlAuthError(
            f"Token Lidl Plus non valido (HTTP {res.status_code}, {body.get('error', 'risposta inattesa')}): "
            "ricollega l'account.")
    return body["access_token"], body.get("refresh_token") or refresh_token


def _get(url: str, access_token: str, language: str, timeout: float) -> Any:
    headers = dict(_APP_HEADERS, **{"Authorization": f"Bearer {access_token}",
                                     "Accept-Language": language})
    try:
        res = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as e:
        raise LidlError(f"Lidl Plus non raggiungibile: {e}") from e
    if res.status_code == 401:
        raise LidlAuthError("Lidl Plus ha rifiutato l'accesso: ricollega l'account.")
    if res.status_code >= 400:
        raise LidlError(f"Lidl Plus ha risposto HTTP {res.status_code}")
    return res.json()


def list_tickets(access_token: str, country: str = "IT", language: str = "it",
                 timeout: float = 15) -> List[Dict[str, Any]]:
    """Prima pagina degli scontrini, dal più recente."""
    data = _get(_TICKETS_URL.format(country=country) + "?pageNumber=1&onlyFavorite=False",
                access_token, language, timeout)
    if isinstance(data, dict):
        return data.get("tickets") or data.get("records") or []
    return data or []


def get_ticket(ticket_id: str, access_token: str, country: str = "IT", language: str = "it",
               timeout: float = 15) -> Dict[str, Any]:
    return _get(_TICKET_URL.format(country=country, ticket_id=ticket_id),
                access_token, language, timeout)


def _num(text: Optional[str], default: float = 0.0) -> float:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return default


_ARTICLE_RE = re.compile(r'<span([^>]*\bclass="article"[^>]*)>(.*?)</span>', re.S)


def _attr(attrs: str, name: str) -> Optional[str]:
    m = re.search(rf'\b{name}="([^"]*)"', attrs)
    return _html.unescape(m.group(1)).strip() if m else None


def parse_html_receipt(html_content: str) -> List[Dict[str, Any]]:
    """Articoli dello scontrino HTML (formato Lidl Italia).

    Un articolo comprato in più pezzi occupa DUE righe con gli stessi attributi:
    'YOMO DELT.YOG.GR.MIR  10%  2,58' e sotto 'Cad 1,29 Pz. 2'. Si tiene solo la
    riga che inizia con la descrizione, altrimenti lo stesso yogurt conta doppio.
    """
    items = []
    for m in _ARTICLE_RE.finditer(html_content or ""):
        attrs, text = m.group(1), _html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        desc = _attr(attrs, "data-art-description")
        if not desc or not text.upper().startswith(desc.upper()[:12]):
            continue   # riga di dettaglio ("Cad 1,29 Pz. 2", peso al kg) o non articolo
        qty = _num(_attr(attrs, "data-art-quantity"), 1.0) or 1.0
        weighed = abs(qty - round(qty)) > 1e-6          # 0,532 = kg pesati alla cassa
        items.append({
            "article_id": _attr(attrs, "data-art-id") or "",
            "name": desc,
            "quantity": 1.0 if weighed else qty,
            "weight_kg": qty if weighed else None,
            "unit_price": _num(_attr(attrs, "data-unit-price")),
        })
    return items


def extract_items(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Articoli da un dettaglio scontrino, strutturato (itemsLine) o HTML."""
    if detail.get("itemsLine"):
        out = []
        for it in detail["itemsLine"]:
            qty = _num(it.get("quantity"), 1.0) or 1.0
            weighed = bool(it.get("isWeight")) or abs(qty - round(qty)) > 1e-6
            out.append({
                "article_id": str(it.get("codeInput") or it.get("articleId") or ""),
                "name": str(it.get("name") or "").strip(),
                "quantity": 1.0 if weighed else qty,
                "weight_kg": qty if weighed else None,
                "unit_price": _num(it.get("currentUnitPrice") or it.get("originalAmount")),
            })
        return [i for i in out if i["name"]]
    return parse_html_receipt(detail.get("htmlPrintedReceipt") or "")
