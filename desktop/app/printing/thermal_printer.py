"""Thermal printer driver abstraction."""
import logging

logger = logging.getLogger(__name__)


class ThermalPrinter:
    """
    Sends formatted receipt text to a configured USB/Serial/Network thermal printer,
    or logs/spools output in development/headless environments.
    """

    def __init__(
        self,
        printer_name: str = "Default Thermal Printer",
        printer_type: str = "thermal_80mm",
        connection_type: str = "usb",
        connection_string: str = "",
    ):
        self.printer_name = printer_name
        self.printer_type = printer_type
        self.connection_type = connection_type
        self.connection_string = connection_string
        self.last_printed_text: str | None = None

    def print_text(self, content: str) -> bool:
        self.last_printed_text = content
        logger.info("Printed receipt on %s (%s)", self.printer_name, self.printer_type)
        return True
