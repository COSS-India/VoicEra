import JSZip from "jszip";
import { downloadBlob } from "@/lib/report";

/** Build a ZIP from named entries and trigger a browser download. */
export async function downloadZip(
  filename: string,
  entries: Array<{ path: string; data: Blob | ArrayBuffer | string }>,
): Promise<void> {
  const zip = new JSZip();
  for (const entry of entries) {
    zip.file(entry.path, entry.data);
  }
  const blob = await zip.generateAsync({ type: "blob" });
  downloadBlob(blob, "application/zip", filename);
}
