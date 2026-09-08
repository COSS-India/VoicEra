import { ButtonHTMLAttributes, forwardRef } from "react";

type Variant = "primary" | "dark" | "outline" | "ghost" | "pill-link" | "danger-outline";
type Size = "sm" | "md";

const base =
  "inline-flex items-center justify-center gap-2 font-semibold transition-colors duration-[120ms] ease-out cursor-pointer disabled:cursor-not-allowed disabled:opacity-45";

const sizes: Record<Size, string> = {
  sm: "text-xs px-3 py-2 rounded-v-md",
  md: "text-[13px] px-[17px] py-[11px] rounded-v-md",
};

const variants: Record<Variant, string> = {
  primary: "bg-v-accent text-white shadow-[var(--v-shadow-primary)] hover:bg-v-accent-deep",
  dark: "bg-v-fg text-white hover:bg-v-accent",
  outline:
    "bg-white border border-v-line-strong text-v-fg hover:bg-v-fg hover:text-white hover:border-v-fg",
  ghost: "bg-transparent border border-v-line text-v-body hover:bg-v-track hover:border-v-line-strong",
  "pill-link": "bg-white border border-v-line text-v-fg hover:border-v-accent hover:bg-v-soft",
  "danger-outline": "bg-transparent border border-v-danger text-v-danger hover:bg-v-danger-pale",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

export const IconButton = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement>>(
  function IconButton({ className = "", ...props }, ref) {
    return (
      <button
        ref={ref}
        className={`inline-flex size-[34px] items-center justify-center rounded-v-md border border-v-line text-v-body transition-colors duration-[120ms] ease-out hover:bg-v-track hover:border-v-line-strong cursor-pointer disabled:cursor-not-allowed disabled:opacity-45 ${className}`}
        {...props}
      />
    );
  },
);
