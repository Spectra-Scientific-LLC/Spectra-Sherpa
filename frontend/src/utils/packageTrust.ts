import type { DeployApplication } from "@/types";

export function packageTrustLabel(status: DeployApplication["package_trust"]): string {
  if (status === "verified") return "Signature verified";
  if (status === "unsigned") return "Imported package · Unsigned";
  return "Signature not verified";
}

export function packageTrustHint(status: DeployApplication["package_trust"]): string {
  return status === "verified"
    ? "Publisher signature verified at import; this is not approval for an intended use."
    : status === "unsigned"
      ? "No publisher signature; package integrity and model compatibility are still checked."
      : "Publisher authentication was not established for this import.";
}
