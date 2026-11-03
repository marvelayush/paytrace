import { AuthGate } from "@/components/auth-gate";

// Who is signed in is only known in the browser (the session cookie belongs to the API),
// so these screens cannot be prerendered for instant navigation. Opt out of that check.
export const instant = false;

export default function SignedInLayout({ children }: { children: React.ReactNode }) {
  return <AuthGate>{children}</AuthGate>;
}
