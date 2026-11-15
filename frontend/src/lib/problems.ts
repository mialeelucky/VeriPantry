// Map gateway problems to a sentence and, where useful, a next step (frontend.md §5.2).

import { ApiProblem } from "../api/client";

export function problemMessage(e: unknown): string {
  if (!(e instanceof ApiProblem)) return "Something went wrong. Try again.";
  switch (e.code) {
    case "insufficient-role":
      return `This needs a higher role. ${e.detail ?? ""}`.trim();
    case "approval-not-pending":
      return "This request was already decided or has expired.";
    case "reason-required":
      return "Enter a reason first.";
    case "upstream-unavailable":
      return "The supplier's system didn't answer. Try again in a moment.";
    case "budget-exceeded":
      return "Too many requests this hour. Wait a little and try again.";
    case "network-unreachable":
      return "Can't reach VeriPantry. Check that the servers are running.";
    case "invalid-request":
      return `The request isn't complete: ${e.detail ?? e.title}`;
    case "token-missing":
    case "token-invalid":
      return "Your session has ended. Sign in again.";
    default:
      return e.detail ? `${e.title}. ${e.detail}` : e.title;
  }
}
