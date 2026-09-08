import { PageHeader, Section } from "@/components/PageHeader";
import { Button, IconButton } from "@/components/ui/Button";
import { Input, Select, Textarea, Label } from "@/components/ui/Field";
import { Card, StatCard } from "@/components/ui/Card";
import { Badge, Tag } from "@/components/ui/Badge";
import { SwitchDemo } from "@/components/ui/Switch";
import { Spinner } from "@/components/ui/Spinner";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { InfoTip } from "@/components/ui/Tooltip";
import { Toast } from "@/components/ui/Toast";
import { ModalDemo, DropdownDemo } from "@/components/ui/Modal";
import { Stepper } from "@/components/ui/Stepper";
import { NavRailDemo } from "@/components/ui/NavRail";

export default function ComponentsPage() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-2 px-8 py-12">
      <PageHeader
        eyebrow="VoicEra"
        title="Components"
        description="Reusable primitives found across the sign-in, agent wizard, and dashboard screens, each shown with its variants."
      />

      <Section title="Buttons" description="Primary, outline, ghost, pill-link, and icon variants.">
        <Button variant="primary">Continue creating the agent</Button>
        <Button variant="outline">← Back to agents</Button>
        <Button variant="ghost">Discard changes</Button>
        <Button variant="pill-link">Open dashboard</Button>
        <Button variant="danger-outline">Revoke</Button>
        <Button variant="primary" disabled>
          Sending
        </Button>
        <IconButton aria-label="Expand">»</IconButton>
      </Section>

      <Section title="Inputs" description="Text, email, select, and textarea, all with focus states.">
        <div className="flex w-full max-w-sm flex-col gap-2">
          <Label htmlFor="c-email">Email</Label>
          <Input id="c-email" type="email" placeholder="you@example.com" />
        </div>
        <div className="flex w-full max-w-sm flex-col gap-2">
          <Label htmlFor="c-zone">Timezone</Label>
          <Select id="c-zone" defaultValue="Asia/Kolkata">
            <option>Asia/Kolkata</option>
            <option>Asia/Kathmandu</option>
            <option>Asia/Dhaka</option>
          </Select>
        </div>
        <div className="flex w-full flex-col gap-2">
          <Label htmlFor="c-inst">Instructions</Label>
          <Textarea
            id="c-inst"
            placeholder="Describe how the agent should behave on a call…"
          />
        </div>
      </Section>

      <Section title="Cards" description="Panel cards and stat cards used for agents, documents, and campaigns.">
        <Card className="flex w-72 flex-col gap-2 p-4.5">
          <span className="flex items-center justify-between gap-2">
            <span className="text-[14.5px] font-semibold">Mandi price line</span>
            <Badge tone="live">Live</Badge>
          </span>
          <span className="text-xs font-light text-v-muted">
            Kannada · Hindi · Tamil — 3 languages, updated daily.
          </span>
        </Card>
        <StatCard label="Calls this week" value="4,208" note="+12% vs last week" />
      </Section>

      <Section title="Badges & tags" description="State pills and category tags.">
        <Badge tone="live">Live</Badge>
        <Badge tone="draft">Draft</Badge>
        <Badge tone="accent">Beta</Badge>
        <Badge tone="danger">Failed</Badge>
        <Tag>Escalation</Tag>
        <Tag>Compliance</Tag>
      </Section>

      <Section title="Toggle switch">
        <div className="flex items-center gap-3">
          <SwitchDemo defaultChecked label="Email me a daily summary" />
          <span className="text-xs text-v-muted">Email me a daily summary</span>
        </div>
        <div className="flex items-center gap-3">
          <SwitchDemo label="SMS alerts" />
          <span className="text-xs text-v-muted">SMS alerts</span>
        </div>
      </Section>

      <Section title="Loading spinner" description="Used inside submit buttons while a request is in flight.">
        <span className="flex items-center gap-2 rounded-full bg-v-fg px-4.5 py-3 text-sm font-semibold text-white">
          <Spinner />
          Sending
        </span>
      </Section>

      <Section title="Progress bar" description="Upload and campaign progress.">
        <div className="flex w-full max-w-sm flex-col gap-2">
          <ProgressBar pct={64} thick />
          <span className="font-mono text-[10.5px] text-v-muted">64% · 1,340 of 2,090</span>
        </div>
      </Section>

      <Section title="Tooltip">
        <span className="flex items-center gap-2 text-sm">
          Voice temperature <InfoTip text="Higher values make the agent's phrasing less predictable call to call." />
        </span>
      </Section>

      <Section title="Toast notification">
        <Toast
          title="Agent published"
          note="Mandi price line is now live on +91 80 4718 2200."
          action="View"
        />
      </Section>

      <Section title="Modal & dropdown menu">
        <ModalDemo />
        <DropdownDemo />
      </Section>

      <Section title="Stepper" description="Four-step progress control from the agent wizard.">
        <Stepper />
      </Section>

      <Section title="Nav rail" description="Collapsible sidebar navigation used across the dashboard and wizard.">
        <NavRailDemo />
      </Section>
    </main>
  );
}
