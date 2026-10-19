import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui-style input, dark-world finish: a recessed well (darker than the
 * plate it sits on) with the cyan instrument light on focus.
 */
export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        "flex h-10 w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm shadow-[inset_0_1px_2px_hsl(214_56%_4%/0.4)] transition-[border-color,box-shadow] placeholder:text-muted-foreground/70 focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-transparent disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      ref={ref}
      {...props}
    />
  )
);
Input.displayName = "Input";

export { Input };
