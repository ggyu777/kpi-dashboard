#!/usr/bin/env python3
"""GA4 OAuth 토큰 발급/갱신 → token.json 저장 + Vercel용 한 줄 JSON 출력.

사용:
  .venv/bin/python scripts/oauth-ga4-token.py
  .venv/bin/python scripts/oauth-ga4-token.py --push-vercel   # 발급 후 Vercel Production 반영
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parent.parent
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
DEFAULT_SECRET = ROOT / "client_secret.json"
TOKEN_PATH = ROOT / "token.json"


def find_client_secret() -> Path:
    if secret := Path(__file__).resolve().parent.joinpath("..", "client_secret.json").resolve():
        if secret.exists():
            return secret
    matches = sorted(ROOT.glob("client_secret_*.json"))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        "client_secret.json 이 없습니다. Google Cloud Console에서 OAuth Desktop client JSON을 받아 프로젝트 루트에 두세요."
    )


def issue_token(client_secret: Path) -> dict:
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    data = json.loads(creds.to_json())
    if not data.get("refresh_token"):
        print(
            "경고: refresh_token 이 없습니다. Google 계정 → 타사 앱 액세스에서 이 앱 연결을 해제한 뒤 다시 실행하세요.",
            file=sys.stderr,
        )
    return data


def push_vercel(token_line: str) -> None:
    print("\n[Vercel] Production GOOGLE_TOKEN_JSON 업데이트 중...")
    subprocess.run(
        ["vercel", "env", "rm", "GOOGLE_TOKEN_JSON", "production", "--yes"],
        cwd=ROOT,
        check=False,
    )
    proc = subprocess.run(
        ["vercel", "env", "add", "GOOGLE_TOKEN_JSON", "production"],
        cwd=ROOT,
        input=token_line + "\n",
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("vercel env add 실패 — Vercel Dashboard에서 GOOGLE_TOKEN_JSON을 수동으로 붙여넣어 주세요.")
    print("[Vercel] 환경변수 저장 완료. 재배포를 실행합니다...")
    subprocess.run(["vercel", "--prod", "--yes"], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="GA4 OAuth token 발급")
    parser.add_argument("--client-secret", type=Path, default=None, help="OAuth client JSON 경로")
    parser.add_argument("--push-vercel", action="store_true", help="발급 후 Vercel Production에 반영 및 재배포")
    args = parser.parse_args()

    secret = args.client_secret or find_client_secret()
    print(f"OAuth client: {secret.name}")
    print("브라우저가 열리면 GA4 속성에 접근 가능한 Google 계정으로 로그인하세요.\n")

    token = issue_token(secret)
    TOKEN_PATH.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")
    token_line = json.dumps(token, ensure_ascii=False, separators=(",", ":"))

    print(f"\n저장: {TOKEN_PATH}")
    print("\n--- Vercel GOOGLE_TOKEN_JSON (한 줄, 복사용) ---")
    print(token_line)
    print("--- 끝 ---\n")

    # 로컬 검증
    test = subprocess.run(
        ["npx", "tsx", "scripts/test-ga4.ts"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if test.returncode == 0:
        print(test.stdout.strip())
        print("로컬 GA4 연결 OK")
    else:
        print(test.stdout)
        print(test.stderr, file=sys.stderr)
        print("로컬 GA4 테스트 실패 — GA4 속성 뷰어 권한을 확인하세요.", file=sys.stderr)

    if args.push_vercel:
        push_vercel(token_line)


if __name__ == "__main__":
    main()
