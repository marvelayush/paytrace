import type { Metadata } from "next";

import { UploadsView } from "@/components/uploads/uploads-view";

export const metadata: Metadata = { title: "Uploads" };
export const instant = false;

export default function UploadsPage() {
  return <UploadsView />;
}
