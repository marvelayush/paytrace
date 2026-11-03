/** Shapes returned by the PayTrace API. Money is integer paise; percentages are basis points. */

export type PartnerKind = "website" | "marketplace" | "quickcom" | "courier" | "warehouse";

export type Partner = {
  id: number;
  name: string;
  kind: PartnerKind;
  settlement_days: number;
};

export type FreightLeg = "forward" | "return";

export type WeightSlab = {
  leg: FreightLeg;
  up_to_g: number;
  price_paise: number;
};

export type RateCardTerms = {
  effective_from: string;
  commission_pct_bp: number;
  fixed_fee_paise: number;
  cod_fee_paise: number;
  cod_fee_pct_bp: number;
  gateway_pct_bp: number;
  tcs_pct_bp: number;
  tds_pct_bp: number;
  slabs: WeightSlab[];
};

export type RateCard = RateCardTerms & {
  id: number;
  partner_id: number;
};

export const PARTNER_KIND_LABELS: Record<PartnerKind, string> = {
  website: "Own website",
  marketplace: "Marketplace",
  quickcom: "Quick commerce",
  courier: "Courier",
  warehouse: "Warehouse",
};
