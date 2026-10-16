"use client";

import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { ExtractedValue } from "@/lib/types";

export type PageLayout = "itemized" | "continuous";

type Box = { left: number; top: number; width: number; height: number };

/**
 * Renders one source page and highlights where each extracted value is.
 *
 * Renderer contract (so real page images can replace the simulation):
 *  - "simulated" (today): the page is the issuer's `printed_content`. A value's location is its
 *    character span in that text; the location box is measured from where that span is actually drawn,
 *    so it always lines up with what the reviewer sees.
 *  - "image" (future): the page is a scan; the location box comes from the extracted value's
 *    `position` (page fractions). Highlights, selection and the value panel work unchanged.
 */
export function PageSurface({
  text, values, selectedId, onSelect, showBox, layout, title, pageLabel,
}: {
  text: string;
  values: ExtractedValue[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  showBox: boolean;
  layout: PageLayout;
  title: string;
  pageLabel: string;
}) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const selectedRef = useRef<HTMLElement | null>(null);
  const [box, setBox] = useState<Box | null>(null);

  const measure = useCallback(() => {
    const body = bodyRef.current;
    const mark = selectedRef.current;
    if (!body || !mark || !mark.isConnected) return setBox(null);
    const rects = Array.from(mark.getClientRects());
    if (!rects.length) return setBox(null);
    const origin = body.getBoundingClientRect();
    const left = Math.min(...rects.map((r) => r.left));
    const top = Math.min(...rects.map((r) => r.top));
    const right = Math.max(...rects.map((r) => r.right));
    const bottom = Math.max(...rects.map((r) => r.bottom));
    const pad = 3;
    setBox({
      left: left - origin.left + body.scrollLeft - pad,
      top: top - origin.top + body.scrollTop - pad,
      width: right - left + pad * 2,
      height: bottom - top + pad * 2,
    });
  }, []);

  // Re-measure whenever what is drawn can move: selection, text, layout, size.
  useLayoutEffect(() => {
    measure();
  }, [measure, selectedId, text, layout]);
  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    const ro = new ResizeObserver(measure);
    ro.observe(body);
    return () => ro.disconnect();
  }, [measure]);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedId, text]);

  // Non-overlapping highlight segments from value spans (offsets are into the unmodified text).
  const spans = values
    .filter((v) => v.span)
    .map((v) => ({ start: v.span![0], end: v.span![1], v }))
    .sort((a, b) => a.start - b.start || b.end - a.end);
  const segments: React.ReactNode[] = [];
  let cursor = 0;
  const plain = (s: string, key: string) => segments.push(<PlainText key={key} text={s} layout={layout} />);
  for (const s of spans) {
    if (s.start < cursor) continue; // overlapping reading of the same characters: first wins
    if (s.start > cursor) plain(text.slice(cursor, s.start), `t${cursor}`);
    const selected = s.v.id === selectedId;
    const conflict = s.v.flags.some((f) => f.severity === "conflict");
    const review = s.v.flags.some((f) => f.severity === "review");
    const verified = (s.v.verifications?.length ?? 0) > 0;
    segments.push(
      <mark
        key={s.v.id}
        ref={selected ? (el) => { selectedRef.current = el; } : undefined}
        onClick={() => onSelect(s.v.id)}
        title={`${s.v.id} · ${s.v.label}`}
        data-ev={s.v.id}
        className={cn(
          "cursor-pointer rounded-[3px] px-0.5 transition-colors",
          selected ? "bg-sky-200 text-slate-900"
            : conflict ? "bg-rose-100 text-rose-900 underline decoration-rose-400 decoration-wavy"
            : review ? "bg-amber-100 text-amber-900"
            : verified ? "bg-emerald-100/80 text-slate-900"
            : "bg-yellow-50 text-slate-900 hover:bg-sky-100",
        )}
      >
        {text.slice(s.start, s.end)}
      </mark>,
    );
    cursor = s.end;
  }
  if (cursor < text.length) plain(text.slice(cursor), `t${cursor}`);
  if (!values.some((v) => v.id === selectedId && v.span)) selectedRef.current = null;

  return (
    <div className="mx-auto flex aspect-[8.5/11] w-full max-w-[680px] flex-col overflow-hidden rounded-sm bg-white shadow-[0_1px_3px_rgba(0,0,0,0.12),0_8px_24px_rgba(15,23,42,0.06)] ring-1 ring-slate-200">
      <div className="flex items-center justify-between border-b border-dashed border-slate-200 px-8 pt-6 pb-2 text-[10px] uppercase tracking-wider text-slate-400">
        <span className="truncate">{title}</span>
        <span className="shrink-0">{pageLabel}</span>
      </div>
      <div
        ref={bodyRef}
        className={cn(
          "relative min-h-0 flex-1 overflow-y-auto px-8 py-5 font-mono text-[12.5px] text-slate-800 whitespace-pre-wrap break-words",
          layout === "itemized" ? "leading-[1.75]" : "leading-[1.9]",
        )}
      >
        {segments}
        {showBox && box && (
          <div
            aria-hidden
            className="pointer-events-none absolute rounded-[4px] border-2 border-sky-600 shadow-[0_0_0_3px_rgba(2,132,199,0.15)]"
            style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
          />
        )}
      </div>
    </div>
  );
}

/**
 * Plain (un-highlighted) printed text. In the itemized layout the space after each item separator
 * ("; ", " | ", or a sentence end) is drawn as a line break. Nothing else changes: every printed
 * character is rendered in order, and highlight offsets still index the unmodified `printed_content`.
 */
const ITEM_BREAK = /(; | \| |\.\s(?=[A-Z(\d]))/;
const NOT_SENTENCE_END = /\b(?:Inc|Co|Corp|Ltd|LLC|LLP|Ave|St|Rd|Dr|Blvd|No|Mr|Mrs|Ms|Jr|Sr|vs|approx|U\.S)$/;

function PlainText({ text, layout }: { text: string; layout: PageLayout }) {
  if (layout === "continuous") return <>{text}</>;
  const parts = text.split(ITEM_BREAK);
  return (
    <>
      {parts.map((part, i) => {
        const isSep = i % 2 === 1;
        if (!isSep) return <Fragment key={i}>{part}</Fragment>;
        const before = parts[i - 1] ?? "";
        const breakHere = part !== ". " && part !== ".\n" ? true : !NOT_SENTENCE_END.test(before);
        return (
          <Fragment key={i}>
            {part.trimEnd()}
            {breakHere ? "\n" : part.slice(part.trimEnd().length)}
          </Fragment>
        );
      })}
    </>
  );
}
