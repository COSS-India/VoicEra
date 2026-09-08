import { NextRequest, NextResponse } from "next/server";
import type { AgentForm } from "@/lib/wizard-data";

interface CreateAgentBody {
  form?: AgentForm;
  asTemplate?: boolean;
}

interface CreatedAgent {
  id: string;
  name: string;
  purpose: string;
  langs: string[];
  status: "Live" | "Template";
  createdAt: string;
}

// In-memory store — resets on server restart. UI-kit demo, not a real database.
const createdAgents: CreatedAgent[] = [];

export async function GET() {
  return NextResponse.json({ ok: true, agents: createdAgents });
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as CreateAgentBody;
  const { form, asTemplate } = body;

  if (!form || !form.name) {
    return NextResponse.json(
      { ok: false, error: "The agent needs a name before it can be created." },
      { status: 400 },
    );
  }

  const agent: CreatedAgent = {
    id: `agent_${Date.now().toString(36)}`,
    name: form.name,
    purpose: form.purpose || form.prompt.slice(0, 80),
    langs: form.langs,
    status: asTemplate ? "Template" : "Live",
    createdAt: new Date().toISOString(),
  };

  createdAgents.push(agent);

  return NextResponse.json({ ok: true, agent }, { status: 201 });
}
