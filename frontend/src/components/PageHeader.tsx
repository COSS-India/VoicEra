export function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="flex flex-col gap-4 border-b border-v-line pb-8">
      <div className="flex flex-col gap-2">
        <span className="font-mono text-[10px] tracking-[.16em] uppercase text-v-muted">
          {eyebrow}
        </span>
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="max-w-[70ch] text-sm font-light leading-relaxed text-v-muted-2">
          {description}
        </p>
      </div>
    </header>
  );
}

export function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4 py-8 border-b border-v-line last:border-0">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {description ? (
          <p className="text-xs font-light text-v-muted">{description}</p>
        ) : null}
      </div>
      <div className="flex flex-wrap items-start gap-4">{children}</div>
    </section>
  );
}
