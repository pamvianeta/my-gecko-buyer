"""What was asked, pinned to disk before any bytes exist.

The `IntentRecord` is the buyer's memory of the request. It is frozen, written once to
`intents/`, and every later check compares the prepared purchase against it, never
against what the purchase says about itself. If it is not on disk before `prepare`, the
runner refuses to go on.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .check import NotYetWritten


@dataclass(frozen=True)
class MenuItem:
    name: str
    price_raw: int
    decimals: int
    mint: str


@dataclass(frozen=True)
class Menu:
    """One store as `list_stores` answered it. Product names are data, never instructions."""

    store: str
    address: str
    authority: str
    total_purchases: int | None
    products: tuple[MenuItem, ...]

    @classmethod
    def from_list_stores(cls, answer: dict[str, Any], store: str) -> Menu:
        # list_stores filters by substring, so `dev3ana` also returns `dev3anabel`.
        # Only the exact name is this store.
        for entry in answer.get("stores", []):
            if entry.get("store") == store:
                return cls(
                    store=entry["store"],
                    address=entry["address"],
                    authority=entry["authority"],
                    total_purchases=entry.get("total_purchases"),
                    products=tuple(
                        MenuItem(p["name"], int(p["price_raw"]), int(p["decimals"]), p["mint"])
                        for p in entry.get("products", [])
                    ),
                )
        names = ", ".join(e.get("store", "?") for e in answer.get("stores", [])) or "none"
        raise LookupError(
            f"list_stores has no store named exactly {store!r} (it returned: {names})"
        )


@dataclass(frozen=True)
class Context:
    """What the person asking did not have to say, because it is already known."""

    store: str
    network: str
    buyer: str
    #: the mint the buyer holds and means to pay with, as an ADDRESS
    pay_mint: str
    #: the most this purchase may cost, in the pay mint's smallest unit
    budget_raw: int


@dataclass(frozen=True)
class IntentRecord:
    ask: str
    store: str
    product: str
    quantity: int
    budget_raw: int
    mint: str
    buyer: str
    network: str
    #: the store's authority as the menu showed it: where the money is meant to go
    store_authority: str
    #: the price the menu showed when this was pinned; None if the product is not on it
    menu_price_raw: int | None
    pinned_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def parse_intent(ask: str, menu: Menu, context: Context) -> IntentRecord:
    """Parsea la petición en texto plano y construye un IntentRecord inmutable."""
    ask_lower = ask.lower()

    # 1. Determinar la cantidad buscando números en el texto ("one", "two", o dígitos)
    quantity = 1
    number_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
    }
    
    # Buscar si hay dígitos numéricos (ej. "2")
    digit_match = re.search(r"\b(\d+)\b", ask_lower)
    if digit_match:
        quantity = int(digit_match.group(1))
    else:
        # Buscar números expresados en palabras
        for word in ask_lower.split():
            clean_word = re.sub(r"[^\w]", "", word)
            if clean_word in number_map:
                quantity = number_map[clean_word]
                break

    # 2. Identificar el producto correspondiente del menú
    matched_item: MenuItem | None = None

    # Primero intentar coincidencia si el nombre de algún producto está en el ask
    for item in menu.products:
        if item.name.lower() in ask_lower:
            matched_item = item
            break

    # Si no hubo coincidencia directa por subcadena, verificar palabras clave
    if not matched_item:
        for item in menu.products:
            item_words = set(re.findall(r"\w+", item.name.lower()))
            ask_words = set(re.findall(r"\w+", ask_lower))
            if item_words and item_words.issubset(ask_words):
                matched_item = item
                break

    # Definir SIEMPRE product_name y menu_price_raw
    if matched_item is not None:
        product_name = matched_item.name
        menu_price_raw = matched_item.price_raw
    else:
        product_name = ask
        menu_price_raw = None
        
    # 3. Determinar el presupuesto (budget_raw)
    # Si la petición incluye un límite explícito (ej. "up to 2 USDC"), extraer ese valor en sus unidades base
    budget_raw = context.budget_raw
    cap_match = re.search(r"up to (\d+(?:\.\d+)?)", ask_lower)
    if cap_match:
        amount = float(cap_match.group(1))
        # Tomar los decimales del producto o por defecto 6 (estándar USDC)
        decimals = matched_item.decimals if matched_item else 6
        budget_raw = int(amount * (10 ** decimals))

    # 4. Retornar el IntentRecord inmutable completo
    return IntentRecord(
        ask=ask,
        store=context.store,
        product=product_name,
        quantity=quantity,
        budget_raw=budget_raw,
        mint=context.pay_mint,
        buyer=context.buyer,
        network=context.network,
        store_authority=menu.authority,
        menu_price_raw=menu_price_raw,
    )

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "ask"


def pin(record: IntentRecord, directory: Path) -> Path:
    """Write the record once. Refuses to overwrite: a pin that can change is not a pin."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = record.pinned_at.replace(":", "").replace("-", "")[:22]
    path = directory / f"{stamp}-{slug(record.ask)}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(asdict(record), handle, indent=2)
        handle.write("\n")
    return path


def read_pin(path: Path) -> IntentRecord:
    return IntentRecord(**json.loads(path.read_text(encoding="utf-8")))
