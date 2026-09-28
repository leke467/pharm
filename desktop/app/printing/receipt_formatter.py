"""Thermal receipt formatter for 58mm (32 cols) and 80mm (48 cols) printers."""
from decimal import Decimal


class ReceiptFormatter:
    """Formats POS sales receipts for thermal printers or plain-text preview."""

    def __init__(self, width: int = 48):
        self.width = width

    def _center(self, text: str) -> str:
        return text.center(self.width)

    def _kv(self, left: str, right: str) -> str:
        space = max(1, self.width - len(left) - len(right))
        return f"{left}{' ' * space}{right}"

    def format_sale_receipt(
        self,
        *,
        organization_name: str,
        branch_name: str,
        branch_address: str = "",
        branch_phone: str = "",
        receipt_number: str,
        sale_date: str,
        cashier_name: str,
        customer_name: str | None = None,
        items: list[dict],
        subtotal: Decimal | str,
        discount_amount: Decimal | str,
        tax_amount: Decimal | str,
        total: Decimal | str,
        payments: list[dict],
        currency: str = "NGN",
        is_reprint: bool = False,
    ) -> str:
        sep = "-" * self.width
        dsep = "=" * self.width
        lines = [
            self._center(organization_name.upper()),
            self._center(branch_name),
        ]
        if branch_address:
            lines.append(self._center(branch_address))
        if branch_phone:
            lines.append(self._center(f"Tel: {branch_phone}"))
        if is_reprint:
            lines.append(self._center("*** REPRINT COPY ***"))

        lines.extend([
            dsep,
            self._kv("Receipt #:", receipt_number),
            self._kv("Date:", str(sale_date)[:19].replace("T", " ")),
            self._kv("Cashier:", cashier_name),
        ])
        if customer_name:
            lines.append(self._kv("Customer:", customer_name))
        lines.append(sep)
        lines.append(self._kv("ITEM (QTY x PRICE)", f"TOTAL ({currency})"))
        lines.append(sep)

        for item in items:
            name = str(item.get("product_name", "Item"))[: self.width]
            qty = item.get("quantity", 1)
            u_price = Decimal(str(item.get("unit_price", "0.00"))).quantize(Decimal("0.01"))
            l_total = Decimal(str(item.get("line_total", "0.00"))).quantize(Decimal("0.01"))
            batch_no = item.get("batch_number", "")
            lines.append(name)
            detail_left = f"  {qty} x {u_price}" + (f" [Batch: {batch_no}]" if batch_no else "")
            lines.append(self._kv(detail_left, f"{l_total:.2f}"))

        lines.append(sep)
        lines.append(self._kv("Subtotal:", f"{Decimal(str(subtotal)):.2f}"))
        if Decimal(str(discount_amount)) > 0:
            lines.append(self._kv("Discount:", f"-{Decimal(str(discount_amount)):.2f}"))
        if Decimal(str(tax_amount)) > 0:
            lines.append(self._kv("Tax:", f"{Decimal(str(tax_amount)):.2f}"))
        lines.append(dsep)
        lines.append(self._kv(f"TOTAL ({currency}):", f"{Decimal(str(total)):.2f}"))
        lines.append(dsep)

        for p in payments:
            method = str(p.get("payment_method", "CASH")).upper()
            amt = Decimal(str(p.get("amount", "0.00"))).quantize(Decimal("0.01"))
            lines.append(self._kv(f"Paid ({method}):", f"{amt:.2f}"))

        lines.extend([
            sep,
            self._center("Thank you for your patronage!"),
            self._center("Get well soon."),
            "",
        ])
        return "\n".join(lines)
