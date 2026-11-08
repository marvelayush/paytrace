import type { Metadata } from "next";

import { ReturnsView } from "@/components/returns/returns-view";

export const metadata: Metadata = { title: "Returns" };
export const instant = false;

export default function ReturnsPage() {
  return <ReturnsView />;
}
