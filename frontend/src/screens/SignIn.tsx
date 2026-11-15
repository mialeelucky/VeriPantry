// Demo persona picker (frontend.md §4.3).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChefHat, ShieldCheck, Wallet } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { gatewayApi } from "../api/gateway";
import { useSession } from "../auth/session";
import { Notice, Spinner } from "../components/ui";
import { problemMessage } from "../lib/problems";

const ICONS: Record<string, typeof ChefHat> = { u_chef: ChefHat, u_fin: Wallet, u_valio: ShieldCheck };

export default function SignIn() {
  const { signIn } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const personas = useQuery({ queryKey: ["personas"], queryFn: gatewayApi.personas });

  async function choose(id: string) {
    setError(null);
    try {
      const person = await signIn(id);
      const next = params.get("next");
      navigate(next && next.startsWith("/") ? next : person.kind === "staff" ? "/audit" : "/approvals", { replace: true });
    } catch (e) {
      setError(problemMessage(e));
    }
  }

  return (
    <div className="vp-step mx-auto w-full max-w-[420px]">
      <h1 className="text-[22px] font-medium">Who's using this device?</h1>
      <p className="mt-1 text-ink-2">Demo sign-in. Choose a person to continue.</p>
      {personas.isLoading && <div className="mt-6"><Spinner label="Loading" /></div>}
      {(personas.isError || error) && (
        <div className="mt-4">
          <Notice tone="stop">{error ?? problemMessage(personas.error)}</Notice>
        </div>
      )}
      <ul className="mt-5 space-y-2.5">
        {personas.data?.map((p) => {
          const Icon = ICONS[p.id] ?? ShieldCheck;
          return (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => choose(p.id)}
                className="flex w-full items-center gap-3 rounded-[14px] border border-line bg-surface p-4 text-left hover:border-line-strong"
              >
                <span className="flex size-10 items-center justify-center rounded-full bg-muted text-ink-2">
                  <Icon className="size-5" aria-hidden />
                </span>
                <span>
                  <span className="block font-medium">{p.displayName}</span>
                  <span className="block text-[13px] text-ink-2">
                    {p.kind === "staff" ? "Valio Aimo · auditor" : `Hotel 123 · ${p.role === "admin" ? "approves any amount" : "approves up to €5,000"}`}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
