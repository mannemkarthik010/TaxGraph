"use client";

import Link from "next/link";
import { Suspense, use } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Loading, PageHeader } from "@/components/tp/primitives";
import { LineDrawerProvider, SCHEDULE_TITLES } from "@/components/tp/schedules/common";
import { ScheduleView } from "@/components/tp/schedules/schedule-view";

export default function RecordPage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = use(params);
  return <Suspense fallback={<Loading />}><Record name={name} /></Suspense>;
}

function Record({ name }: { name: string }) {
  const version = useSearchParams().get("v") ?? "v3";
  return (
    <LineDrawerProvider version={version}>
      <Link href={`/return?tab=records&v=${version}`} className="inline-flex items-center gap-1 text-xs text-sky-700 hover:underline"><ArrowLeft className="size-3" />All records</Link>
      <PageHeader title={SCHEDULE_TITLES[name] ?? name} subtitle={`Return ${version}. Every figure links to its line; TaxProof's own recalculations are shown separately from the engine.`} />
      <ScheduleView name={name} version={version} />
    </LineDrawerProvider>
  );
}
