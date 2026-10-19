import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-[background-color,border-color,color,box-shadow] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // The instrument light: solid brand cyan with navy ink — the primary
        // action on any plate. Hover deepens toward the brand cyan.
        default: "bg-primary text-primary-foreground shadow-[0_1px_2px_hsl(214_56%_4%/0.5)] hover:bg-primary/90 active:bg-primary/80",
        destructive:
          "bg-destructive text-destructive-foreground shadow-[0_1px_2px_hsl(214_56%_4%/0.5)] hover:bg-destructive/90",
        warning: "bg-warning text-warning-foreground shadow-[0_1px_2px_hsl(214_56%_4%/0.5)] hover:bg-warning/90",
        outline:
          "border border-input bg-transparent hover:border-primary/40 hover:bg-secondary/70 hover:text-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/70",
        // Ghost hovers on the raised tint — never on the accent: the cyan is
        // reserved for actions, focus and links (see tailwind.config.ts).
        ghost: "hover:bg-secondary/70 hover:text-foreground",
        link: "text-primary underline-offset-4 hover:text-accent hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

/**
 * shadcn/ui-style button (cva pattern), dark-world finish. Defaults to
 * type="button" so buttons outside forms never submit implicitly; pass
 * type="submit" in forms.
 *
 * For links styled as buttons use `buttonVariants({ ... })` on next/link —
 * this scaffold has no Radix Slot dependency.
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", ...props }, ref) => (
    <button type={type} className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  )
);
Button.displayName = "Button";

export { Button, buttonVariants };
