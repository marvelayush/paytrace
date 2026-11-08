"""All SQLAlchemy models. Importing this package registers every table on Base.metadata (needed by Alembic)."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.claim import Claim, ClaimItem
from app.models.ledger import CodRemittance, FreightLine, Order, SettlementLine, WarehouseReceipt
from app.models.partner import ColumnMapping, Partner, Source
from app.models.rate_card import RateCard, WeightSlab
from app.models.recon import ReconResult, ReconRun
from app.models.review import ManualReturnReceipt, UnmatchedLine
from app.models.upload import Upload, UploadRowError
from app.models.user import User

__all__ = [
    "AuditLog",
    "Base",
    "Claim",
    "ClaimItem",
    "CodRemittance",
    "ColumnMapping",
    "FreightLine",
    "ManualReturnReceipt",
    "Order",
    "Partner",
    "RateCard",
    "ReconResult",
    "ReconRun",
    "SettlementLine",
    "Source",
    "Upload",
    "UnmatchedLine",
    "UploadRowError",
    "User",
    "WarehouseReceipt",
]
