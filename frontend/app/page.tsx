import type { Metadata } from "next";
import PublicLanding from "@/components/public-landing";

export const metadata: Metadata = {
  title: "PyLake — One platform. Every data.",
  description:
    "An open-source lakehouse for data ingestion, transformation, orchestration, SQL analytics, and data management.",
};

export default function HomePage() {
  return <PublicLanding />;
}
