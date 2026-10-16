"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Search as SearchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/api";
import type { SearchResponse } from "@/lib/ai-types";
import { Chip, ErrorState, Loading, PageHeader, Panel } from "@/components/tp/primitives";
import { refHref } from "@/components/tp/ai/claims";

const EXAMPLES = ["Show me everything supporting the California move.", "Why did tax increase from v2 to v3?",
                  "Show unresolved basis issues.", "Which values came from low-confidence extractions?"];

export default function SearchPage() {
  return <Suspense fallback={<Loading />}><SearchView /></Suspense>;
}

function SearchView() {
  const params = useSearchParams();
  const router = useRouter();
  const q = params.get("q") ?? "";
  const [text, setText] = useState(q);
  const { data, error } = useApi<SearchResponse>(q.length >= 2 ? `/api/search?q=${encodeURIComponent(q)}` : null);
  const go = (s: string) => { setText(s); router.replace(`/search?q=${encodeURIComponent(s)}`); };
  return (
    <div className="space-y-4">
      <PageHeader title="Search" subtitle="Everything in the packet and the workpaper. Recognised questions get a computed answer; everything else is ranked text search with tax concepts, blended with semantic similarity learned from this file." />
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim().length >= 2) go(text.trim()); }}>
        <Input aria-label="Search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about the return…" className="h-9" />
        <Button type="submit"><SearchIcon className="size-4" />Search</Button>
      </form>
      <div className="flex flex-wrap gap-1.5">
        {EXAMPLES.map((x) => <button key={x} onClick={() => go(x)} className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700 hover:bg-slate-200">{x}</button>)}
      </div>
      <ErrorState error={error} />
      {q && !data && !error && <Loading />}
      {data && (
        <>
          {data.answer && (
            <Panel title={data.answer.title} actions={<Chip tone="info">computed answer</Chip>}>
              <p className="text-[13px]">{data.answer.text}</p>
              <ul className="mt-2 space-y-1 text-[13px]">
                {data.answer.items.slice(0, 30).map((i) => (
                  <li key={i.ref}><Link href={i.link || refHref(i.ref)} className="text-sky-700 hover:underline">{i.title}</Link> <span className="text-xs text-muted-foreground">— {i.detail}</span></li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] text-muted-foreground">Source: {data.answer.source}</p>
            </Panel>
          )}
          <Panel dense title={`${data.results.length} results`} actions={(data.expanded_with.length > 0 || (data.associated ?? []).length > 0) && (
            <span className="text-[11px] text-muted-foreground">
              {data.expanded_with.length > 0 && <>tax concepts: {data.expanded_with.slice(0, 8).join(", ")}</>}
              {(data.associated ?? []).length > 0 && <> · learned from this file: {(data.associated ?? []).slice(0, 6).map((a) => a.term).join(", ")}</>}
            </span>)}>
            <ul className="divide-y text-[13px]">
              {data.results.map((r) => (
                <li key={r.ref} className="px-4 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Chip tone={r.kind === "Engine diagnostic" ? "engine" : r.kind === "TaxProof finding" ? "info" : "neutral"}>{r.kind}</Chip>
                    <Link href={r.link || refHref(r.ref)} className="font-medium hover:underline">{r.title}</Link>
                    <span className="font-mono text-[10.5px] text-slate-400">{r.ref}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-600">{r.snippet}</p>
                  <p className="text-[10.5px] text-muted-foreground">
                    {r.matched.length > 0 ? <>matched: {r.matched.join(", ")}</> : <>no shared words</>}
                    {(r.related ?? []).length > 0 && <> · semantically related{r.semantic != null && <> ({r.semantic.toFixed(2)})</>}: {(r.related ?? []).join(", ")}</>}
                  </p>
                </li>
              ))}
            </ul>
          </Panel>
          <p className="text-[11px] text-muted-foreground">{data.method}</p>
        </>
      )}
    </div>
  );
}
