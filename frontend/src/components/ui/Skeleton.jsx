import { cn } from "@/lib/utils";

/**
 * Shimmer skeleton block. Use as a placeholder while data loads.
 *
 * <Skeleton className="h-6 w-32" />
 * <SkeletonCard />   // 흔한 카드 자리표시
 */
export function Skeleton({ className = "" }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "block rounded-md bg-white/[0.04] relative overflow-hidden",
        "before:absolute before:inset-0 before:-translate-x-full",
        "before:bg-gradient-to-r before:from-transparent before:via-white/8 before:to-transparent",
        "before:animate-[shimmer_1.4s_infinite]",
        className,
      )}
    />
  );
}

export function SkeletonText({ lines = 3, className = "" }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-3", i === lines - 1 ? "w-4/6" : "w-full")}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className = "" }) {
  return (
    <div className={cn("glass rounded-2xl p-5 space-y-4", className)}>
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 rounded-xl" />
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-3 w-16 ml-auto" />
      </div>
      <SkeletonText lines={3} />
      <div className="grid grid-cols-3 gap-2">
        <Skeleton className="h-9" />
        <Skeleton className="h-9" />
        <Skeleton className="h-9" />
      </div>
    </div>
  );
}
