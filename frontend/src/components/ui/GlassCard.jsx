import { forwardRef } from "react";
import { cn } from "@/lib/utils";

export const GlassCard = forwardRef(function GlassCard({ className, ...rest }, ref) {
  return <div ref={ref} className={cn("glass rounded-2xl p-6", className)} {...rest} />;
});
