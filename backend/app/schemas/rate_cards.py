from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BP = 10_000  # 100%
MAX_PAISE = 10_000_000  # ₹1,00,000: far above any realistic per-order fee


class PartnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    settlement_days: int


class WeightSlabIn(BaseModel):
    leg: Literal["forward", "return"]
    up_to_g: int = Field(gt=0, le=100_000)
    price_paise: int = Field(ge=0, le=MAX_PAISE)


class WeightSlabOut(WeightSlabIn):
    model_config = ConfigDict(from_attributes=True)


class RateCardTerms(BaseModel):
    effective_from: date
    commission_pct_bp: int = Field(0, ge=0, le=MAX_BP)
    fixed_fee_paise: int = Field(0, ge=0, le=MAX_PAISE)
    cod_fee_paise: int = Field(0, ge=0, le=MAX_PAISE)
    cod_fee_pct_bp: int = Field(0, ge=0, le=MAX_BP)
    gateway_pct_bp: int = Field(0, ge=0, le=MAX_BP)
    tcs_pct_bp: int = Field(0, ge=0, le=MAX_BP)
    tds_pct_bp: int = Field(0, ge=0, le=MAX_BP)
    slabs: list[WeightSlabIn] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def slabs_are_unique_per_leg(self) -> "RateCardTerms":
        seen: set[tuple[str, int]] = set()
        for slab in self.slabs:
            key = (slab.leg, slab.up_to_g)
            if key in seen:
                raise ValueError(f"Two {slab.leg} slabs both go up to {slab.up_to_g} g.")
            seen.add(key)
        return self


class RateCardCreate(RateCardTerms):
    partner_id: int


class RateCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    partner_id: int
    effective_from: date
    commission_pct_bp: int
    fixed_fee_paise: int
    cod_fee_paise: int
    cod_fee_pct_bp: int
    gateway_pct_bp: int
    tcs_pct_bp: int
    tds_pct_bp: int
    slabs: list[WeightSlabOut]
