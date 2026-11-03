"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type { Partner, RateCard, RateCardTerms, WeightSlab } from "@/lib/types";

export function usePartners() {
  return useQuery<Partner[], ApiError>({
    queryKey: ["partners"],
    queryFn: () => apiFetch<Partner[]>("/partners"),
    staleTime: 5 * 60_000,
  });
}

export function useRateCards() {
  return useQuery<RateCard[], ApiError>({
    queryKey: ["rate-cards"],
    queryFn: () => apiFetch<RateCard[]>("/rate-cards"),
  });
}

export function useSaveRateCard() {
  const queryClient = useQueryClient();
  return useMutation<RateCard, ApiError, { cardId: number | null; partnerId: number; terms: RateCardTerms }>({
    mutationFn: ({ cardId, partnerId, terms }) =>
      cardId === null
        ? apiFetch<RateCard>("/rate-cards", { method: "POST", body: JSON.stringify({ ...terms, partner_id: partnerId }) })
        : apiFetch<RateCard>(`/rate-cards/${cardId}`, { method: "PUT", body: JSON.stringify(terms) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rate-cards"] }),
  });
}

export type SlabRow = { up_to_g: number; forward: number | null; return: number | null };

/** Forward and return slabs side by side, one row per weight limit. */
export function slabRows(slabs: WeightSlab[]): SlabRow[] {
  const rows = new Map<number, SlabRow>();
  for (const slab of slabs) {
    const row = rows.get(slab.up_to_g) ?? { up_to_g: slab.up_to_g, forward: null, return: null };
    row[slab.leg] = slab.price_paise;
    rows.set(slab.up_to_g, row);
  }
  return [...rows.values()].sort((a, b) => a.up_to_g - b.up_to_g);
}

/** The card in force today: the latest whose effective date is not in the future. */
export function currentCard(cards: RateCard[]): RateCard | undefined {
  const today = new Date().toISOString().slice(0, 10);
  const sorted = [...cards].sort((a, b) => b.effective_from.localeCompare(a.effective_from));
  return sorted.find((card) => card.effective_from <= today) ?? sorted[sorted.length - 1];
}
