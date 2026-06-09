/**
 * 로컬 data/kpi-store.json → Vercel Blob 업로드 (1회)
 * 사용: BLOB_READ_WRITE_TOKEN=... npx tsx scripts/upload-store-to-blob.ts
 */
import fs from "fs";
import path from "path";
import { put } from "@vercel/blob";

const file = path.join(process.cwd(), "data", "kpi-store.json");
if (!fs.existsSync(file)) {
  console.error("data/kpi-store.json 없음");
  process.exit(1);
}
const content = fs.readFileSync(file, "utf8");
const result = await put("kpi-store.json", content, {
  access: "public",
  addRandomSuffix: false,
});
console.log("업로드 완료:", result.url);
