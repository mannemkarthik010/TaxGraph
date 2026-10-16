"use client";

import { useApi } from "@/lib/api";
import type {
  BooksToTax, Brokerage, Carryovers, Depreciation, K1Basis, PriorYear, Rentals, StateAllocation, TaxComputation,
} from "@/lib/schedule-types";
import { ErrorState, Loading } from "../primitives";
import { BrokerageView } from "./brokerage";
import { BooksToTaxView, CarryoversView, DepreciationView, PriorYearView, TaxComputationView } from "./financial";
import { K1BasisView, RentalsView } from "./rentals-k1";
import { StateAllocationView } from "./state";

/** Fetches one schedule for a return version and renders it. */
export function ScheduleView({ name, version, activity }: { name: string; version: string; activity?: "Business" | "Rental" }) {
  const { data, error } = useApi<unknown>(`/api/workpaper/schedules/${name}?version=${version}`);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading rows={6} />;
  switch (name) {
    case "tax-computation": return <TaxComputationView data={data as TaxComputation} />;
    case "prior-year": return <PriorYearView data={data as PriorYear} />;
    case "books-to-tax": return <BooksToTaxView data={data as BooksToTax} />;
    case "depreciation": return <DepreciationView data={data as Depreciation} activity={activity} />;
    case "brokerage": return <BrokerageView data={data as Brokerage} />;
    case "rentals": return <RentalsView data={data as Rentals} />;
    case "k1-basis": return <K1BasisView data={data as K1Basis} />;
    case "state-allocation": return <StateAllocationView data={data as StateAllocation} />;
    case "carryovers": return <CarryoversView data={data as Carryovers} />;
    default: return <p className="text-sm text-muted-foreground">Unknown schedule.</p>;
  }
}
