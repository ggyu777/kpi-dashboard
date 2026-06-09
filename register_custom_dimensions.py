"""
GA4 커스텀 측정기준 등록 스크립트.
click_home_ad_banner 이벤트의 placement 파라미터 등록.
1회만 실행하면 됨.
"""
import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as AuthRequest
from google.analytics.admin_v1alpha import AnalyticsAdminServiceClient
from google.analytics.admin_v1alpha.types import (
    CustomDimension,
)

load_dotenv()

TOKEN_FILE = "token.json"
PROPERTY_ID = os.getenv("GA4_PROPERTY_ID", "410384180")


def get_admin_client() -> AnalyticsAdminServiceClient:
    creds = Credentials.from_authorized_user_file(TOKEN_FILE)
    if creds.expired and creds.refresh_token:
        creds.refresh(AuthRequest())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return AnalyticsAdminServiceClient(credentials=creds)


# 등록할 커스텀 측정기준 목록
CUSTOM_DIMENSIONS = [
    {
        "parameter_name": "placement",
        "display_name": "광고 배치 위치",
        "description": "click_home_ad_banner: top(상단카테고리) | popup(팝업) | center(스타일) | bottom(매거진)",
        "scope": CustomDimension.DimensionScope.EVENT,
    },
    {
        "parameter_name": "ad_id",
        "display_name": "광고 ID",
        "description": "click_home_ad_banner 이벤트의 광고 ID",
        "scope": CustomDimension.DimensionScope.EVENT,
    },
    {
        "parameter_name": "ad_name",
        "display_name": "광고 이름",
        "description": "click_home_ad_banner 이벤트의 광고 이름",
        "scope": CustomDimension.DimensionScope.EVENT,
    },
    {
        "parameter_name": "action_type",
        "display_name": "광고 액션 타입",
        "description": "click_home_ad_banner 이벤트의 액션 타입",
        "scope": CustomDimension.DimensionScope.EVENT,
    },
]


def list_existing_dimensions(client, parent):
    existing = {}
    for dim in client.list_custom_dimensions(parent=parent):
        existing[dim.parameter_name] = dim
    return existing


def register_custom_dimensions():
    client = get_admin_client()
    parent = f"properties/{PROPERTY_ID}"

    print(f"GA4 속성 {parent} 커스텀 측정기준 현황 확인 중...\n")
    existing = list_existing_dimensions(client, parent)

    for dim_config in CUSTOM_DIMENSIONS:
        param = dim_config["parameter_name"]

        if param in existing:
            print(f"  ✅ [{param}] 이미 등록됨 → 건너뜀")
            continue

        dimension = CustomDimension(
            parameter_name=param,
            display_name=dim_config["display_name"],
            description=dim_config["description"],
            scope=dim_config["scope"],
        )

        result = client.create_custom_dimension(
            parent=parent, custom_dimension=dimension
        )
        print(f"  ✅ [{param}] 등록 완료: {result.display_name}")

    print("\n등록 완료. GA4 리포트에서 최대 24시간 내 반영됩니다.")
    print("이후 '맞춤 측정기준'에서 확인: https://analytics.google.com")


if __name__ == "__main__":
    register_custom_dimensions()
