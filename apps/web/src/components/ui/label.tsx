import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui-style label. A plain <label> — the Radix label primitive is not
 * part of this scaffold's dependency set; styling parity is what forms need.
 */
const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
        className
      )}
      {...props}
    />
  )
);
Label.displayName = "Label";

export { Label };
