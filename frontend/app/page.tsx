import type { Metadata } from "next";
import PublicLanding from "@/components/public-landing";

export const metadata: Metadata = {
  title: "PyLake — Build. Analyze. Innovate.",
  description:
    "Unify data engineering, lakehouse analytics and optional AI-powered intelligence in one platform built for the next generation of data teams.",
};

export default function HomePage() {
  return <PublicLanding />;
}
