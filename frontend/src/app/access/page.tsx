import { ShieldCheck } from "lucide-react";

export default async function AccessPage({ searchParams }: { searchParams: Promise<{ next?: string; error?: string }> }) {
  const { next = "/overview", error } = await searchParams;
  return (
    <div className="mx-auto mt-24 max-w-sm space-y-4 rounded-lg border bg-card p-6 shadow-xs">
      <div className="flex items-center gap-2 text-lg font-semibold"><ShieldCheck className="size-5 text-primary" />TaxProof</div>
      <p className="text-sm text-muted-foreground">This demo is shared by link. Enter the access code you were given.</p>
      <form method="post" action="/access/verify" className="space-y-3">
        <input type="hidden" name="next" value={next} />
        <input name="code" type="password" required autoFocus aria-label="Access code" placeholder="Access code"
          className="h-9 w-full rounded-md border px-3 text-sm" />
        {error && <p className="text-xs text-rose-700">That code is not right.</p>}
        <button type="submit" className="h-9 w-full rounded-md bg-primary text-sm font-medium text-primary-foreground">Continue</button>
      </form>
    </div>
  );
}
