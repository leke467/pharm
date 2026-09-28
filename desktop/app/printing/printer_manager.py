"""Printer manager coordinating PrinterConfiguration and ReceiptFormatter outside DB transactions."""
import logging
from desktop.app.db.models import PrinterConfiguration
from desktop.app.printing.receipt_formatter import ReceiptFormatter
from desktop.app.printing.thermal_printer import ThermalPrinter

logger = logging.getLogger(__name__)


class PrinterManager:
    """
    Manages local receipt printing outside the SQLite sale transaction
    (Architecture Plan §7.1: Print Receipt OUTSIDE transaction so printer faults never abort a sale).
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.last_receipt_text: str | None = None

    def get_default_printer(self, branch_id: str | None = None) -> ThermalPrinter:
        with self.db_manager.get_session() as db:
            q = db.query(PrinterConfiguration).filter_by(is_active=True, is_default=True)
            if branch_id:
                q = q.filter_by(branch_id=branch_id)
            cfg = q.first()
            if cfg:
                return ThermalPrinter(
                    printer_name=cfg.printer_name,
                    printer_type=cfg.printer_type,
                    connection_type=cfg.connection_type,
                    connection_string=cfg.connection_string,
                )
        return ThermalPrinter()

    def print_sale_receipt(self, receipt_context: dict, branch_id: str | None = None) -> str:
        printer = self.get_default_printer(branch_id)
        width = 32 if printer.printer_type == "thermal_58mm" else 48
        formatter = ReceiptFormatter(width=width)
        text = formatter.format_sale_receipt(**receipt_context)
        self.last_receipt_text = text
        try:
            printer.print_text(text)
        except Exception as exc:
            logger.error("Printer error (sale remains committed): %s", exc)
        return text
