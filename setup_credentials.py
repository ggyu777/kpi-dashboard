"""
GA4 인증 설정 스크립트
한 번만 실행하면 token.json이 생성되고 이후 자동 갱신됩니다.

사전 준비:
  1. GCP Console → API 및 서비스 → 사용자 인증 정보
  2. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱)
  3. JSON 다운로드 → 이 폴더에 client_secret.json 으로 저장

실행:
  python setup_credentials.py
"""

import json
import sys
import webbrowser
from pathlib import Path

CLIENT_SECRET_FILE = Path(__file__).parent / "client_secret.json"
TOKEN_FILE = Path(__file__).parent / "token.json"

# GA4 Data API + Admin API 통합 스코프
SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",   # Data API (대시보드용)
    "https://www.googleapis.com/auth/analytics.edit",       # Admin API (dimension 등록용)
]


def check_requirements():
    try:
        import google_auth_oauthlib  # noqa
    except ImportError:
        print("❌ google-auth-oauthlib 가 없습니다. 설치 중...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-auth-oauthlib"])
        print("✅ 설치 완료\n")


def run_oauth_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    # 기존 token.json 확인
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds.valid:
            print("✅ 이미 유효한 token.json이 있습니다.")
            _print_info(creds)
            return
        if creds.expired and creds.refresh_token:
            print("🔄 토큰 갱신 중...")
            try:
                creds.refresh(Request())
                TOKEN_FILE.write_text(creds.to_json())
                print("✅ 토큰 갱신 완료")
                _print_info(creds)
                return
            except Exception as e:
                print(f"⚠️  갱신 실패 ({e}), 재인증합니다.")

    # client_secret.json 확인 (없으면 client_secret_*.json 자동 탐색)
    secret_file = CLIENT_SECRET_FILE
    if not secret_file.exists():
        candidates = sorted(Path(__file__).parent.glob("client_secret_*.json"))
        if candidates:
            secret_file = candidates[0]
            print(f"📎 OAuth 클라이언트 파일 사용: {secret_file.name}")
    if not secret_file.exists():
        print("❌ client_secret.json 파일이 없습니다.\n")
        print("📋 발급 방법:")
        print("   1. https://console.cloud.google.com/apis/credentials 접속")
        print("   2. 상단 '+ 사용자 인증 정보 만들기' → 'OAuth 클라이언트 ID'")
        print("   3. 애플리케이션 유형: '데스크톱 앱'")
        print("   4. 만들기 → JSON 다운로드")
        print(f"   5. 이 폴더에 '{CLIENT_SECRET_FILE.name}' 로 저장\n")
        print("   ※ Google Analytics Data API v1 이 활성화되어 있어야 합니다:")
        print("      https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com")
        webbrowser.open("https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    print("🌐 브라우저에서 Google 계정으로 로그인하세요...")
    print("   (GA4 속성에 접근 가능한 계정으로 로그인)\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", open_browser=True)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"\n✅ 인증 완료! token.json 저장됨: {TOKEN_FILE}")
    _print_info(creds)

    print("\n🚀 이제 대시보드를 실행하세요:")
    print("   python main.py")


def _print_info(creds):
    print(f"   스코프: {', '.join(creds.scopes or [])}")
    if hasattr(creds, "expiry") and creds.expiry:
        print(f"   만료: {creds.expiry.strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    check_requirements()
    run_oauth_flow()
