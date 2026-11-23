import { FileArchive, FileImage, FileSpreadsheet, FileText } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Recognisable, non-preview file representation.
 *
 * The document API streams bytes only through an authorised download endpoint,
 * so generating a thumbnail in the list would mean fetching every file and
 * expanding its access window. A typed tile plus extension is honest about what
 * the file is without pretending to be a preview.
 */
export function FileTypeIcon({
  filename,
  contentType,
  className,
}: {
  filename: string;
  contentType?: string | null;
  className?: string;
}) {
  const extension =
    filename.split(".").pop()?.toUpperCase().slice(0, 4) || "FILE";
  const type = (contentType ?? "").toLowerCase();
  const isImage =
    type.startsWith("image/") || /\.(png|jpe?g|webp|gif|heic)$/i.test(filename);
  const isPdf = type === "application/pdf" || extension === "PDF";
  const isSheet =
    type.includes("spreadsheet") ||
    type.includes("csv") ||
    /\.(xlsx?|csv|ods)$/i.test(filename);
  const isArchive =
    type.includes("zip") ||
    type.includes("compressed") ||
    /\.(zip|rar|7z|tar|gz)$/i.test(filename);

  const { Icon, tone } = isImage
    ? { Icon: FileImage, tone: "bg-info-soft text-info" }
    : isPdf
      ? { Icon: FileText, tone: "bg-destructive/10 text-destructive" }
      : isSheet
        ? { Icon: FileSpreadsheet, tone: "bg-success-soft text-success" }
        : isArchive
          ? { Icon: FileArchive, tone: "bg-warning-soft text-warning" }
          : { Icon: FileText, tone: "bg-primary/10 text-primary" };

  return (
    <span
      className={cn(
        "inline-flex h-10 w-9 shrink-0 flex-col items-center justify-center gap-0.5 rounded-md border border-border/60",
        tone,
        className,
      )}
      aria-hidden="true"
    >
      <Icon className="h-4 w-4" />
      <span className="text-[7px] font-bold tracking-wide">{extension}</span>
    </span>
  );
}
