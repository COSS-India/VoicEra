const TYPE_BORDER: Record<string, string> = {
  adapter: "border-v-ok text-v-ok-ink bg-v-ok-tint",
  cloud: "border-v-accent text-v-accent bg-v-pale",
  local: "border-v-warn text-v-warn-ink bg-v-warn-tint",
};

/** Cloud / adapter / local — same chip used on Integrations and provider pickers. */
export function ProviderTypeBadge({ providerType }: { providerType?: string | null }) {
  if (!providerType) return null;
  const key = providerType.toLowerCase();
  const label = providerType.charAt(0).toUpperCase() + providerType.slice(1);
  const tone = TYPE_BORDER[key] ?? "border-v-line text-v-muted-2 bg-v-soft";
  return (
    <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${tone}`}>
      {label}
    </span>
  );
}
