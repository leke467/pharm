from dataclasses import dataclass
from datetime import date
from desktop.app.domain.exceptions import InsufficientStockError, ValidationError
from shared.enums import BatchStatus


@dataclass
class BatchStock:
    batch_id: str
    batch_number: str
    expiry_date: str
    received_date: str
    status: str
    available_quantity: int


@dataclass
class BatchAllocation:
    batch_id: str
    batch_number: str
    expiry_date: str
    quantity: int


def select_batches_fefo(
    available_batches: list[BatchStock],
    qty_needed: int,
    today_iso: str | None = None,
) -> list[BatchAllocation]:
    """
    First Expiry First Out (FEFO) batch selection (Architecture Plan §7.4).
    - Sorts candidate batches by `expiry_date ASC, received_date ASC`.
    - Strictly skips EXPIRED, RECALLED, DEPLETED, or past-expiry batches.
    - Raises InsufficientStockError if total eligible available stock < qty_needed.
    """
    if qty_needed <= 0:
        raise ValidationError("Quantity needed must be positive.")

    today_str = today_iso or date.today().isoformat()
    sorted_batches = sorted(
        available_batches,
        key=lambda b: (b.expiry_date or "9999-12-31", b.received_date or "9999-12-31"),
    )

    allocations: list[BatchAllocation] = []
    remaining = qty_needed
    for b in sorted_batches:
        if remaining <= 0:
            break
        if b.status != BatchStatus.ACTIVE.value:
            continue
        if b.expiry_date and b.expiry_date < today_str:
            continue
        if b.available_quantity <= 0:
            continue

        take = min(remaining, b.available_quantity)
        allocations.append(
            BatchAllocation(
                batch_id=b.batch_id,
                batch_number=b.batch_number,
                expiry_date=b.expiry_date,
                quantity=take,
            )
        )
        remaining -= take

    if remaining > 0:
        raise InsufficientStockError(
            f"Insufficient eligible stock (short by {remaining} units)."
        )
    return allocations


def select_batches_fifo(
    available_batches: list[BatchStock],
    qty_needed: int,
    today_iso: str | None = None,
) -> list[BatchAllocation]:
    """
    First In First Out (FIFO) batch selection.
    - Sorts candidate batches by `received_date ASC, expiry_date ASC`.
    - Strictly skips EXPIRED, RECALLED, DEPLETED, or past-expiry batches.
    """
    if qty_needed <= 0:
        raise ValidationError("Quantity needed must be positive.")

    today_str = today_iso or date.today().isoformat()
    sorted_batches = sorted(
        available_batches,
        key=lambda b: (b.received_date or "9999-12-31", b.expiry_date or "9999-12-31"),
    )

    allocations: list[BatchAllocation] = []
    remaining = qty_needed
    for b in sorted_batches:
        if remaining <= 0:
            break
        if b.status != BatchStatus.ACTIVE.value:
            continue
        if b.expiry_date and b.expiry_date < today_str:
            continue
        if b.available_quantity <= 0:
            continue

        take = min(remaining, b.available_quantity)
        allocations.append(
            BatchAllocation(
                batch_id=b.batch_id,
                batch_number=b.batch_number,
                expiry_date=b.expiry_date,
                quantity=take,
            )
        )
        remaining -= take

    if remaining > 0:
        raise InsufficientStockError(
            f"Insufficient eligible stock (short by {remaining} units)."
        )
    return allocations
