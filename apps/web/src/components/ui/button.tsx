import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-full text-[13.5px] font-semibold tracking-[-0.01em] ring-offset-background transition-[color,background-color,border-color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.97]",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_12px_24px_-16px_hsl(var(--primary)/0.9)] hover:bg-primary/90",
        destructive:
          "border border-destructive/40 bg-destructive/20 text-destructive hover:bg-destructive/25",
        outline:
          "border border-border bg-card/60 text-foreground shadow-sm backdrop-blur-xl hover:bg-card",
        secondary:
          "border border-border bg-secondary/70 text-secondary-foreground hover:bg-secondary",
        ghost: "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 gap-1.5 px-3 text-[12.5px]",
        lg: "h-11 px-6",
        icon: "h-9 w-9",
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
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        // The ripple layer is scoped to text-sized buttons: an icon button is
        // too small for it and several icon buttons carry an overlapping
        // badge that `overflow-hidden` would clip.
        className={cn(
          buttonVariants({ variant, size, className }),
          size !== "icon" && "motion-ripple-host",
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
