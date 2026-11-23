import Image from "next/image";
import { cn } from "@/lib/utils";

interface ScuMarkProps {
  className?: string;
  /** When provided, the mark is exposed as a labelled image. */
  title?: string;
}

/**
 * The institutional seal supplied for SYCUMAIN_V2.
 *
 * The artwork lives at `public/brand/scu-seal.png` with its white paper
 * background keyed out, so it can sit directly on the navy institutional
 * surfaces without a visible plate. It is decorative whenever the wordmark
 * sits beside it and only gets a role/label when used on its own.
 */
export function ScuMark({ className, title }: ScuMarkProps) {
  return (
    <Image
      src="/brand/scu-seal.png"
      alt={title ?? ""}
      aria-hidden={title ? undefined : true}
      width={512}
      height={512}
      sizes="288px"
      className={cn("object-contain", className)}
    />
  );
}
