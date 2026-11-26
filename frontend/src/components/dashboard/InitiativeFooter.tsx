const DOCS_URL = "https://voicera.mintlify.app/docs/guides";

/** "VoicEra · An AI4Inclusion initiative" strip shown at the bottom of the dashboard. */
export function InitiativeFooter() {
  return (
    <footer className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-v-line pt-4 text-[12.5px] text-v-body">
      <div className="flex items-center gap-2">
        <span>VoicEra · An</span>
        {/* eslint-disable-next-line @next/next/no-img-element -- static public brand asset */}
        <img
          src="/ai4i-logo.png"
          alt="AI4Inclusion"
          className="h-7 w-auto shrink-0"
          draggable={false}
        />
        <span>initiative</span>
      </div>
      <nav className="flex items-center gap-1.5">
        <a href={DOCS_URL} target="_blank" rel="noreferrer" className="hover:text-v-fg">
          Docs
        </a>
        <span aria-hidden>·</span>
        <a href="#" className="hover:text-v-fg">
          Privacy
        </a>
        <span aria-hidden>·</span>
        <a href="#" className="hover:text-v-fg">
          Terms
        </a>
      </nav>
    </footer>
  );
}
