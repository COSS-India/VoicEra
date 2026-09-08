"use client";

import { InputHTMLAttributes, useState, TextareaHTMLAttributes } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Select } from "@/components/ui/Select";

const fieldBase =
  "w-full box-border rounded-v-lg border border-v-line-strong bg-white text-v-fg text-[13.5px] px-3.5 py-[11px] placeholder:text-v-dim transition-colors duration-[120ms] ease-out focus:border-v-accent focus:border-[1.5px] focus:shadow-[0_0_0_4px_rgba(31,78,232,0.10)] disabled:cursor-not-allowed disabled:opacity-45";

export function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${fieldBase} ${className}`} {...props} />;
}

/** A password input with an eye icon to toggle plaintext visibility. Pass a full
 * `className` to replace the default pill styling entirely (e.g. to match a
 * differently-styled form); omit it to get the same look as `Input`. */
export function PasswordInput({
  className,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input
        type={visible ? "text" : "password"}
        className={`${className ?? fieldBase} pr-12`}
        {...props}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        tabIndex={-1}
        className="absolute right-2 top-1/2 flex size-8 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg"
      >
        {visible ? <EyeOff className="size-4" strokeWidth={1.75} /> : <Eye className="size-4" strokeWidth={1.75} />}
      </button>
    </div>
  );
}

// Re-exported so existing `import { Select } from "@/components/ui/Field"`
// call sites keep working unchanged — the real implementation now lives in
// ui/Select.tsx (a custom dropdown, not a native <select>) alongside Input/Textarea.
export { Select };

export function Textarea({
  className = "",
  rows = 5,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      rows={rows}
      className={`w-full box-border rounded-v-md border border-v-line-strong bg-white text-v-fg text-sm leading-relaxed px-4 py-3.5 resize-y focus:border-v-accent transition-colors ${className}`}
      {...props}
    />
  );
}

export function Label({
  children,
  htmlFor,
}: {
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <label htmlFor={htmlFor} className="text-[13px] font-semibold text-v-fg">
      {children}
    </label>
  );
}
