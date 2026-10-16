"use client";

import { Check, ChevronDown, ShieldCheck, ShieldOff, UserRound } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApi } from "@/lib/api";
import { useActingUser } from "@/lib/user-context";
import type { Me, UserRow } from "@/lib/types";

const ORDER = ["preparer", "reviewer", "partner", "quality_reviewer", "firm_administrator", "client"];

export function RoleSwitcher() {
  const { userId, setUserId } = useActingUser();
  const { data: users } = useApi<UserRow[]>("/api/session/users");
  const { data: me } = useApi<Me>("/api/session/me");

  const sorted = [...(users ?? [])].sort((a, b) => ORDER.indexOf(a.role) - ORDER.indexOf(b.role));

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-2 rounded-md border bg-white px-2.5 py-1.5 text-left text-sm shadow-xs hover:bg-slate-50">
        <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary">
          <UserRound className="size-4" />
        </span>
        <span className="leading-tight">
          <span className="block text-[13px] font-medium">{me?.name ?? "…"}</span>
          <span className="block text-[11px] text-muted-foreground">Acting as {me?.role_label ?? "…"}</span>
        </span>
        <ChevronDown className="size-4 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          Switch acting user — permissions are enforced by the server
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {sorted.map((u) => (
          <DropdownMenuItem key={u.id} onSelect={() => setUserId(u.id)} className="items-start gap-2 py-2">
            <span className="mt-0.5 w-4">{u.id === userId && <Check className="size-4" />}</span>
            <span className="flex-1">
              <span className="flex items-center gap-1.5 text-[13px] font-medium">
                {u.name}
                {u.credential && <span className="text-[10px] text-muted-foreground">{u.credential}</span>}
              </span>
              <span className="block text-[11px] text-muted-foreground">
                {u.role_label}
                {u.engagement_roles.length > 0 && " · on this engagement"}
                {u.note && ` · ${u.note}`}
              </span>
            </span>
            {u.kind === "staff" &&
              (u.sensitive_data_clearance ? (
                <ShieldCheck className="mt-0.5 size-4 text-emerald-600" aria-label="Sensitive-data clearance" />
              ) : (
                <ShieldOff className="mt-0.5 size-4 text-amber-600" aria-label="No sensitive-data clearance" />
              ))}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
