import { forwardRef } from "react";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonStyles = cva(
  "inline-flex items-center justify-center gap-2 font-medium rounded-full transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/60 disabled:opacity-50 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary:
          "text-white bg-gradient-to-br from-violet via-violet/90 to-magenta/80 hover:shadow-[0_10px_36px_-12px_rgba(139,92,246,0.7)] hover:-translate-y-[1px]",
        ghost: "text-fg-muted hover:text-fg hover:bg-white/5",
        outline: "text-fg border border-white/10 hover:border-violet/40 hover:bg-white/5",
      },
      size: {
        sm: "h-9 px-4 text-sm",
        md: "h-11 px-6 text-sm",
        lg: "h-14 px-8 text-base",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export const Button = forwardRef(function Button(
  { className, variant, size, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(buttonStyles({ variant, size }), className)}
      {...rest}
    />
  );
});
