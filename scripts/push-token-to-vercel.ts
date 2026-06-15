/**
 * 갱신된 token.json → Vercel Production GOOGLE_TOKEN_JSON 반영 + 재배포
 *
 * 사용: npx tsx scripts/push-token-to-vercel.ts
 */
import { execSync } from "child_process";
import fs from "fs";
import path from "path";

const ROOT = process.cwd();
const tokenPath = path.join(ROOT, "token.json");

if (!fs.existsSync(tokenPath)) {
  console.error("token.json 없음. 먼저 scripts/oauth-ga4-token.py 를 실행하세요.");
  process.exit(1);
}

const tokenLine = JSON.stringify(JSON.parse(fs.readFileSync(tokenPath, "utf8")));

try {
  execSync("vercel env rm GOOGLE_TOKEN_JSON production --yes", { cwd: ROOT, stdio: "inherit" });
} catch {
  // 없으면 무시
}

execSync(`vercel env add GOOGLE_TOKEN_JSON production`, {
  cwd: ROOT,
  input: `${tokenLine}\n`,
  stdio: ["pipe", "inherit", "inherit"],
});

console.log("Vercel 재배포 중...");
execSync("vercel --prod --yes", { cwd: ROOT, stdio: "inherit" });
console.log("완료: https://running-life-kpi-dashboard.vercel.app");
