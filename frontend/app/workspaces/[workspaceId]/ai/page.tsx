"use client";

import { use } from "react";
import { AICopilotChat } from "@/components/ai-copilot-chat";

export default function AICopilotPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  return <AICopilotChat workspaceId={workspaceId} />;
}
