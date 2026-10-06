"""The part that says no: seven fields of the prepared purchase against the pinned intent.

Each check returns a `FieldResult`. A refusal names the field and BOTH values: what was
asked (from the pin) and what was found (in the prepared bytes). "Cannot buy" is not a
refusal; "price_raw: asked at most 2000000, prepared 3000000" is.

Two checks are written as worked examples: `check_program` and `check_store`. The other
five are yours. Until you write one it raises `NotYetWritten`, and `check_all` treats that
as a refusal: an unwritten check never lets a signature through.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from solders.pubkey import Pubkey

from . import letmebuy

if TYPE_CHECKING:
    from .intent import IntentRecord
    from .prepared import Prepared


class NotYetWritten(NotImplementedError):
    """A TODO the student has not written yet. Never caught as a pass."""

    def __init__(self, what: str, hint: str) -> None:
        self.what, self.hint = what, hint
        super().__init__(f"{what} is not written yet ({hint})")


@dataclass(frozen=True)
class FieldResult:
    field: str
    ok: bool
    asked: Any
    found: Any
    #: where `found` came from: "prepared", "menu", "signer", "verify"
    where: str = "prepared"
    note: str = ""

    def line(self) -> str:
        if self.ok:
            return f"{self.field}: {self.found!r}"
        text = f"{self.field}: asked {self.asked!r}, {self.where} {self.found!r}"
        return f"{text} ({self.note})" if self.note else text


class Refused(Exception):
    """Raised from any step that decides not to go on. Carries the field that decided."""

    def __init__(self, result: FieldResult) -> None:
        self.result = result
        super().__init__(result.line())


def refuse(
    field_name: str, asked: Any, found: Any, where: str = "prepared", note: str = ""
) -> FieldResult:
    return FieldResult(field_name, False, asked, found, where, note)


def agree(field_name: str, value: Any) -> FieldResult:
    return FieldResult(field_name, True, value, value)


# --- worked example 1 ---------------------------------------------------------------------


def check_program(intent: IntentRecord, prepared: Prepared) -> FieldResult:
    """The bytes call the store program, and nothing else that could move money.

    Compared as an address. `letmebuy.program_id()` comes from the IDL shipped in this
    repo, not from Gecko's answer: the thing being checked never supplies the answer.
    """
    expected = str(letmebuy.program_id())
    if prepared.program != expected:
        return refuse("program", expected, prepared.program)
    if prepared.programs != (expected,):
        return refuse(
            "program", [expected], list(prepared.programs), note="an extra program is called"
        )
    return agree("program", expected)


# --- worked example 2 ---------------------------------------------------------------------


def check_store(intent: IntentRecord, prepared: Prepared) -> FieldResult:
    """The store account is the one DERIVED from the pinned store name.

    Never a constant, and never the address Gecko reported: PDA(['receipts', name]) is
    computed here, from the name the person asked for. A store with a similar name, or a
    swapped account, gives a different address.
    """
    expected = str(letmebuy.store_address(intent.store))
    if prepared.store != expected:
        return refuse("store", f"{intent.store} at {expected}", prepared.store)
    return agree("store", expected)


# --- yours --------------------------------------------------------------------------------
# --- yours --------------------------------------------------------------------------------


def check_product(intent: IntentRecord, prepared: Prepared) -> FieldResult:
    """El producto en la simulación preparada debe ser idéntico al producto en la intención fijada (pin)."""
    asked = intent.product
    found = prepared.product
    if found != asked:
        return refuse("product", asked, found)
    return agree("product", asked)


def check_price(intent: IntentRecord, prepared: Prepared) -> FieldResult:
    """El precio preparado debe ser un entero válido y no superar el presupuesto fijado."""
    asked = intent.budget_raw
    found = prepared.price_raw

    if found is None:
        return refuse("price_raw", asked, "none", note="no price was reported by simulation")

    if found > asked:
        return refuse("price_raw", asked, found)

    return agree("price_raw", found)


def check_mint(intent: IntentRecord, prepared: Prepared) -> FieldResult:
    """La dirección del token mint preparado debe coincidir exactamente con la fijada."""
    asked = str(intent.mint)
    found = str(prepared.mint)
    if found != asked:
        return refuse("mint", asked, found)
    return agree("mint", asked)


def check_quantity(intent: IntentRecord, prepared: Prepared) -> FieldResult:
    """La cantidad preparada debe ser exactamente igual a la cantidad fijada."""
    asked = intent.quantity
    found = prepared.quantity
    if found != asked:
        return refuse("quantity", asked, found)
    return agree("quantity", asked)


def check_destination(intent: IntentRecord, prepared: Prepared) -> FieldResult:
    """La cuenta destino debe ser la Token Account asociada derivada del store_authority y el mint."""
    # Convertir cadenas de texto a objetos Pubkey
    owner_pk = Pubkey.from_string(str(intent.store_authority))
    mint_pk = Pubkey.from_string(str(intent.mint))

    expected = str(
        letmebuy.token_account(
            owner=owner_pk,
            mint=mint_pk,
        )
    )
    found = str(prepared.destination)
    if found != expected:
        return refuse("destination", expected, found)
    return agree("destination", expected)

#: The order is part of the design: cheap, structural checks first.
CHECKS: tuple[Callable[[IntentRecord, Prepared], FieldResult], ...] = (
    check_program,
    check_store,
    check_product,
    check_price,
    check_mint,
    check_quantity,
    check_destination,
)


@dataclass
class Verdict:
    results: list[FieldResult] = field(default_factory=list)
    refusal: FieldResult | None = None
    unwritten: NotYetWritten | None = None

    @property
    def passed(self) -> bool:
        return self.refusal is None and self.unwritten is None


def check_all(intent: IntentRecord, prepared: Prepared) -> Verdict:
    """Run every check in order and stop at the first that does not agree."""
    verdict = Verdict()
    for check in CHECKS:
        try:
            result = check(intent, prepared)
        except NotYetWritten as todo:
            verdict.unwritten = todo
            return verdict
        verdict.results.append(result)
        if not result.ok:
            verdict.refusal = result
            return verdict
    return verdict
