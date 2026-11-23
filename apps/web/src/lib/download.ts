/**
 * Save a fetched blob as a download.
 *
 * Downloads go through the same authenticated fetch as every other request, so
 * a private export never needs a public URL. The object URL is revoked
 * immediately after the click, otherwise the blob is retained for the lifetime
 * of the document.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
