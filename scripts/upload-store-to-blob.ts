/**
 * 로컬 data/kpi-store.json → Vercel Blob 업로드 (1회)
 * 사용: vercel env pull .env.production.local --environment=production
 *       npx tsx scripts/upload-store-to-blob.ts
 */
import fs from "fs";
import path from "path";
import { put } from "@vercel/blob";

function loadEnvFile(name: string) {
  const p = path.join(process.cwd(), name);
  if (!fs.existsSync(p)) return;
  for (const line of fs.readFileSync(p, "utf8").split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (!m || process.env[m[1]]) continue;
    let v = m[2];
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    process.env[m[1]] = v;
  }
}

loadEnvFile(".env.production.local");
loadEnvFile(".env.local");

const file = path.join(process.cwd(), "data", "kpi-store.json");
if (!fs.existsSync(file)) {
  console.error("data/kpi-store.json 없음");
  process.exit(1);
}

if (!process.env.BLOB_READ_WRITE_TOKEN && !process.env.BLOB_STORE_ID) {
  console.error("BLOB_READ_WRITE_TOKEN 또는 BLOB_STORE_ID 필요 (vercel env pull 먼저 실행)");
  process.exit(1);
}

async function main() {
  const content = fs.readFileSync(file, "utf8");
  const result = await put("kpi-store.json", content, {
    access: "public",
    addRandomSuffix: false,
    allowOverwrite: true,
    cacheControlMaxAge: 60,
    contentType: "application/json",
  });
  console.log("업로드 완료:", result.url);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
