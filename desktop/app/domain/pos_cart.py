from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from desktop.app.domain.exceptions import ValidationError


@dataclass
class CartItem:
    """
    POS Cart line item with frozen `unit_price` captured at add-to-cart time
    (Architecture Plan §7.3).
    """

    product_id: str
    product_name: str
    sku: str
    quantity: int
    unit_price: Decimal  # Frozen at add-to-cart time
    discount_amount: Decimal = Decimal("0.00")
    batch_id: str | None = None  # Optional manual batch override
    batch_number: str | None = None
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def line_subtotal(self) -> Decimal:
        return (self.unit_price * Decimal(self.quantity)).quantize(Decimal("0.01"))

    @property
    def line_total(self) -> Decimal:
        tot = self.line_subtotal - self.discount_amount
        return max(Decimal("0.00"), tot.quantize(Decimal("0.01")))


class POSCart:
    """
    In-memory POS Cart maintaining frozen item prices, item discounts, header discount, and tax.
    """

    def __init__(self):
        self.items: list[CartItem] = []
        self.header_discount: Decimal = Decimal("0.00")
        self.tax_amount: Decimal = Decimal("0.00")
        self.customer_name: str = ""
        self.customer_phone: str = ""
        self.notes: str = ""

    def add_item(
        self,
        *,
        product_id: str,
        product_name: str,
        sku: str,
        quantity: int,
        unit_price: Decimal | str | float,
        discount_amount: Decimal | str | float = "0.00",
        batch_id: str | None = None,
        batch_number: str | None = None,
    ) -> CartItem:
        if quantity <= 0:
            raise ValidationError("Item quantity must be at least 1.")
        frozen_price = Decimal(str(unit_price)).quantize(Decimal("0.01"))
        disc = Decimal(str(discount_amount)).quantize(Decimal("0.01"))
        if frozen_price < 0 or disc < 0:
            raise ValidationError("Price and discount cannot be negative.")

        # If same product + batch is already in cart, increment quantity while preserving original frozen unit_price!
        for existing in self.items:
            if existing.product_id == product_id and existing.batch_id == batch_id:
                existing.quantity += quantity
                existing.discount_amount += disc
                return existing

        item = CartItem(
            product_id=product_id,
            product_name=product_name,
            sku=sku,
            quantity=quantity,
            unit_price=frozen_price,
            discount_amount=disc,
            batch_id=batch_id,
            batch_number=batch_number,
        )
        self.items.append(item)
        return item

    def remove_item(self, index: int):
        if 0 <= index < len(self.items):
            self.items.pop(index)

    def clear(self):
        self.items.clear()
        self.header_discount = Decimal("0.00")
        self.tax_amount = Decimal("0.00")
        self.customer_name = ""
        self.customer_phone = ""
        self.notes = ""

    @property
    def subtotal(self) -> Decimal:
        return sum((i.line_subtotal for i in self.items), Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def total_discount(self) -> Decimal:
        item_disc = sum((i.discount_amount for i in self.items), Decimal("0.00"))
        return (item_disc + self.header_discount).quantize(Decimal("0.01"))

    @property
    def total(self) -> Decimal:
        val = self.subtotal - self.total_discount + self.tax_amount
        return max(Decimal("0.00"), val.quantize(Decimal("0.01")))
