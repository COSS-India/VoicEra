export function Toast({
  title,
  note,
  action,
}: {
  title: string;
  note: string;
  action?: string;
}) {
  return (
    <div className="animate-v-pop flex items-start gap-3 rounded-v-sm border border-v-line bg-white px-4 py-3.5 shadow-[0_18px_50px_rgba(11,11,12,.14)]">
      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-v-accent" />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="text-[13.5px] font-semibold">{title}</span>
        <span className="text-xs font-light text-v-muted">{note}</span>
      </span>
      {action ? (
        <button className="ml-auto shrink-0 cursor-pointer text-xs font-medium text-v-accent hover:text-v-accent-deep">
          {action}
        </button>
      ) : null}
    </div>
  );
}
