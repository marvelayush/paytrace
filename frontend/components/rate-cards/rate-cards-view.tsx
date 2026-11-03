"use client";

import { CopyPlus, Info, Pencil } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ErrorState, PageHeader } from "@/components/page-header";
import { RateCardDetail } from "@/components/rate-cards/rate-card-detail";
import { RateCardEditor } from "@/components/rate-cards/rate-card-editor";
import { RecomputeHint } from "@/components/recompute-hint";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { canEdit, useCurrentUser } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { currentCard, usePartners, useRateCards } from "@/lib/rate-cards";
import { PARTNER_KIND_LABELS, type Partner, type RateCard } from "@/lib/types";
import { cn } from "@/lib/utils";

const GROUPS: { label: string; kinds: Partner["kind"][] }[] = [
  { label: "Sales channels", kinds: ["website", "marketplace", "quickcom"] },
  { label: "Couriers", kinds: ["courier"] },
];

export function RateCardsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: user } = useCurrentUser();
  const partners = usePartners();
  const rateCards = useRateCards();

  const [editorMode, setEditorMode] = useState<"edit" | "new-version" | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [chosenCardId, setChosenCardId] = useState<number | null>(null);

  // Partners that have rates (the warehouse sends scans, not invoices).
  const pricedPartners = useMemo(
    () => (partners.data ?? []).filter((partner) => partner.kind !== "warehouse"),
    [partners.data],
  );

  const selectedPartner =
    pricedPartners.find((partner) => String(partner.id) === searchParams.get("partner")) ?? pricedPartners[0];

  const versions: RateCard[] = useMemo(
    () =>
      (rateCards.data ?? [])
        .filter((card) => card.partner_id === selectedPartner?.id)
        .sort((a, b) => b.effective_from.localeCompare(a.effective_from)),
    [rateCards.data, selectedPartner],
  );
  const selectedCard = versions.find((card) => card.id === chosenCardId) ?? currentCard(versions);

  function selectPartner(partnerId: string) {
    setChosenCardId(null);
    router.replace(`/rate-cards?partner=${partnerId}`, { scroll: false });
  }

  const header = (
    <PageHeader
      title="Rate cards"
      description="What each partner is allowed to charge. Expected amounts for every order are worked out from these."
    />
  );

  if (partners.isPending || rateCards.isPending) {
    return (
      <>
        {header}
        <div className="grid gap-6 lg:grid-cols-[14rem_1fr]">
          <div className="hidden space-y-2 lg:block">
            {Array.from({ length: 8 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
          <Skeleton className="h-80 w-full rounded-xl" />
        </div>
      </>
    );
  }

  const error = partners.error ?? rateCards.error;
  if (error) {
    return (
      <>
        {header}
        <ErrorState
          title="Couldn't load rate cards"
          message={error.message}
          onRetry={() => {
            partners.refetch();
            rateCards.refetch();
          }}
        />
      </>
    );
  }

  if (!selectedPartner) {
    return (
      <>
        {header}
        <ErrorState title="No partners set up" message="Run the seed script to create partners and their rate cards." />
      </>
    );
  }

  return (
    <>
      {header}

      {savedAt && <RecomputeHint className="mb-6" onDismiss={() => setSavedAt(null)} />}

      <div className="grid gap-6 lg:grid-cols-[14rem_1fr]">
        {/* Partner picker: list on desktop, dropdown on mobile */}
        <div className="lg:hidden">
          <Select value={String(selectedPartner.id)} onValueChange={selectPartner}>
            <SelectTrigger className="h-10 w-full bg-card" aria-label="Partner">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pricedPartners.map((partner) => (
                <SelectItem key={partner.id} value={String(partner.id)}>
                  {partner.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <nav aria-label="Partners" className="hidden space-y-5 lg:block">
          {GROUPS.map((group) => (
            <div key={group.label}>
              <h2 className="px-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {group.label}
              </h2>
              <ul className="mt-1.5 space-y-0.5">
                {pricedPartners
                  .filter((partner) => group.kinds.includes(partner.kind))
                  .map((partner) => {
                    const active = partner.id === selectedPartner.id;
                    return (
                      <li key={partner.id}>
                        <button
                          type="button"
                          onClick={() => selectPartner(String(partner.id))}
                          aria-current={active ? "true" : undefined}
                          className={cn(
                            "flex h-9 w-full items-center rounded-lg px-2.5 text-left text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
                            active
                              ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                              : "text-foreground/80 hover:bg-accent",
                          )}
                        >
                          {partner.name}
                        </button>
                      </li>
                    );
                  })}
              </ul>
            </div>
          ))}
        </nav>

        <section aria-labelledby="card-title" className="min-w-0 rounded-xl border bg-card">
          <div className="flex flex-col gap-4 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h2 id="card-title" className="text-base font-semibold">
                {selectedPartner.name}
              </h2>
              <p className="text-sm text-muted-foreground">{PARTNER_KIND_LABELS[selectedPartner.kind]}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {versions.length > 1 && selectedCard && (
                <Select value={String(selectedCard.id)} onValueChange={(value) => setChosenCardId(Number(value))}>
                  <SelectTrigger className="h-8 w-auto min-w-44" aria-label="Rate card version">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {versions.map((card) => (
                      <SelectItem key={card.id} value={String(card.id)}>
                        From {formatDate(card.effective_from)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {canEdit(user) && selectedCard && (
                <>
                  <Button variant="outline" size="sm" onClick={() => setEditorMode("new-version")}>
                    <CopyPlus /> New version
                  </Button>
                  <Button size="sm" onClick={() => setEditorMode("edit")}>
                    <Pencil /> Edit
                  </Button>
                </>
              )}
            </div>
          </div>

          <div className="p-5">
            {selectedCard ? (
              <RateCardDetail partner={selectedPartner} card={selectedCard} />
            ) : (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Info className="size-4" aria-hidden /> This partner has no rate card yet, so nothing is deducted for it.
              </p>
            )}
          </div>
        </section>
      </div>

      {editorMode && selectedCard && (
        <RateCardEditor
          key={`${selectedCard.id}-${editorMode}`}
          partner={selectedPartner}
          card={selectedCard}
          mode={editorMode}
          open
          onOpenChange={(open) => !open && setEditorMode(null)}
          onSaved={(saved) => {
            setChosenCardId(saved.id);
            setSavedAt(new Date().toISOString());
          }}
        />
      )}
    </>
  );
}
