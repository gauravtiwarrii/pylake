"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

export type AIPageType =
  | "dashboard"
  | "data"
  | "dataset"
  | "lakehouse"
  | "quality"
  | "lineage"
  | "sql"
  | "pipelines"
  | "catalog"
  | "audit"
  | "workspace"
  | "ai";

export type AIPageContextValue = {
  page_type: AIPageType;
  active_view?: string;
  dataset_id?: string;
  table_id?: string;
  pipeline_id?: string;
  catalog_asset_id?: string;
  sql_text?: string;
  pathname?: string;
};

const AIPageContextValueStore = createContext<AIPageContextValue | null>(null);
const AIPageContextSetter = createContext<((value: AIPageContextValue) => void) | null>(null);

export function pageTypeFromPath(pathname: string): AIPageType {
  if (pathname.includes("/data")) return "data";
  if (pathname.includes("/lakehouse")) return "lakehouse";
  if (pathname.includes("/sql")) return "sql";
  if (pathname.includes("/pipelines")) return "pipelines";
  if (pathname.includes("/catalog")) return "catalog";
  if (pathname.includes("/audit")) return "audit";
  if (pathname.includes("/settings")) return "workspace";
  if (pathname.includes("/ai")) return "ai";
  return "dashboard";
}

export function AIPageContextProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState<AIPageContextValue | null>(null);
  return (
    <AIPageContextSetter.Provider value={setValue}>
      <AIPageContextValueStore.Provider value={value}>{children}</AIPageContextValueStore.Provider>
    </AIPageContextSetter.Provider>
  );
}

export function useAIPageContext(value: Omit<AIPageContextValue, "pathname">) {
  const setValue = useContext(AIPageContextSetter);
  const pathname = usePathname();
  const {
    page_type,
    active_view,
    dataset_id,
    table_id,
    pipeline_id,
    catalog_asset_id,
    sql_text,
  } = value;

  useEffect(() => {
    setValue?.({
      page_type,
      active_view,
      dataset_id,
      table_id,
      pipeline_id,
      catalog_asset_id,
      sql_text,
      pathname,
    });
  }, [
    setValue,
    pathname,
    page_type,
    active_view,
    dataset_id,
    table_id,
    pipeline_id,
    catalog_asset_id,
    sql_text,
  ]);
}

export function useCurrentAIPageContext(pathname: string): AIPageContextValue {
  const value = useContext(AIPageContextValueStore);
  if (value?.pathname === pathname) return value;
  return { page_type: pageTypeFromPath(pathname), pathname };
}
