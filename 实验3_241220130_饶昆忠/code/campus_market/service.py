"""Public application service composed from Experiment 2 modules."""

from .accounts import AccountService
from .listings import ListingService
from .operations import OperationService
from .reports import ReportService
from .reservations import ReservationService


class MarketService(
    AccountService,
    ListingService,
    ReservationService,
    ReportService,
    OperationService,
):
    """Single-process modular backend sharing one transaction boundary."""
