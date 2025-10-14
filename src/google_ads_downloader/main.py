import re
import sys
import traceback
from configparser import ConfigParser
from datetime import datetime, timedelta
from pathlib import Path

from InquirerPy import inquirer

from google_ads_downloader.config import load_config
from google_ads_downloader.core import (
    get_active_campaigns,
    get_demographic_performance,
    get_youtube_video_report,
)


def clean_dataframe(df):
    CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

    def clean_series(series):
        return series.map(lambda x: CONTROL_CHARS.sub("", x) if isinstance(x, str) else x)

    return df.apply(clean_series)


def sanitize_filename(text: str, max_length: int | None = 20) -> str:
    text = text.strip()
    if max_length is not None and max_length > 0:
        text = text[:max_length]
    text = re.sub(r'[\\/*?:"<>|]', "", text)  # 파일명에서 금지된 문자 제거
    text = re.sub(r"\s+", "_", text)  # 공백은 _로
    return text


def parse_customer_ids(raw: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        if "|" in item:
            cid, alias = item.split("|", 1)
            cid = cid.strip()
            alias = alias.strip()
        else:
            cid, alias = item, ""

        if cid:
            entries.append({"id": cid, "alias": alias})

    return entries


def interactive_mode(config: ConfigParser):
    customer_ids_val = config.get("google-ads", "customer_ids", fallback="")
    if not customer_ids_val:
        print("❌ config.ini 의 [google-ads] 섹션이 비어 있습니다. 샘플을 참조해주세요.")
        return

    customer_records = parse_customer_ids(customer_ids_val)
    if not customer_records:
        print("❌ customer_ids 설정을 확인해주세요. 최소 한 개 이상 필요합니다.")
        return

    print("✅ 사용 가능한 CUSTOMER IDS:")
    for record in customer_records:
        if record["alias"]:
            print(f"- {record['alias']} ({record['id']})")
        else:
            print(f"- {record['id']}")

    # 1️⃣ 고객 ID 선택
    selected_customer = inquirer.select(
        message="고객 ID를 선택하세요:",
        choices=[
            {
                "name": f"{record['alias']} ({record['id']})" if record["alias"] else record["id"],
                "value": record,
            }
            for record in customer_records
        ],
    ).execute()
    customer_id = selected_customer["id"]
    customer_alias = selected_customer["alias"]

    # 2️⃣ 캠페인 선택
    enabled_only = inquirer.confirm(
        message="ENABLED 상태의 캠페인만 보시겠습니까?",
        default=True,
    ).execute()

    cam_df = get_active_campaigns(customer_id, enabled_only=enabled_only)
    if cam_df.empty:
        print("⚠️ 캠페인이 없습니다.")
        return

    campaign_choices = [
        {
            "name": f"[{row.campaign_id}] {row.campaign_name}",
            "value": row.campaign_id,
        }
        for _, row in cam_df.iterrows()
    ]

    campaign_id = inquirer.fuzzy(
        message="🎯 캠페인을 선택하세요:",
        choices=campaign_choices,
        instruction="검색어를 입력하세요",
    ).execute()

    # 3️⃣ 액션 선택
    action_name, action = inquirer.select(
        message="무엇을 하시겠습니까?",
        choices=[("게재지면 보고서 생성", 1), ("잠재고객 성과 보고서 생성", 2)],
    ).execute()

    # 4️⃣ 날짜 입력
    start_date = inquirer.text(
        message="시작일을 입력하세요 (YYYY-MM-DD):",
        default=datetime.today().replace(day=1).strftime("%Y-%m-%d"),
    ).execute()

    end_date = inquirer.text(
        message="종료일을 입력하세요 (YYYY-MM-DD):",
        default=(datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
    ).execute()

    # 5️⃣ 데이터 수집 및 저장
    suffix = datetime.strptime(end_date, "%Y-%m-%d").strftime("%y%m%d")
    campaign_row = cam_df[cam_df["campaign_id"] == campaign_id].iloc[0]
    campaign_name_snippet = sanitize_filename(campaign_row["campaign_name"], max_length=None)

    customer_prefix = (
        f"{sanitize_filename(customer_alias, max_length=20)}_{customer_id}" if customer_alias else customer_id
    )
    base_fname = f"{customer_prefix}_{campaign_id}_{campaign_name_snippet}_{suffix}"

    output_dir = Path("res/output")
    output_dir.mkdir(exist_ok=True, parents=True)

    match action:
        case 1:
            df = get_youtube_video_report(customer_id, campaign_id, start_date, end_date)
            fname = output_dir / f"{base_fname}_video.xlsx"
            df = clean_dataframe(df)
            # NOTE: 업로드 서버에서 첫 2줄 공백 여부를 유연하게 처리해야 합니다.
            df.to_excel(fname, index=False, startrow=2)
            print(f"\n✅ 게재지면 보고서가 저장되었습니다:\n📁 {fname.resolve()}")
        case 2:
            gender_df, age_df = get_demographic_performance(customer_id, campaign_id, start_date, end_date)
            gender_path = output_dir / f"{base_fname}_gender.xlsx"
            age_path = output_dir / f"{base_fname}_age.xlsx"
            gender_df = clean_dataframe(gender_df)
            age_df = clean_dataframe(age_df)
            # NOTE: 업로드 서버에서 첫 2줄 공백 여부를 유연하게 처리해야 합니다.
            gender_df.to_excel(gender_path, index=False, startrow=2)
            age_df.to_excel(age_path, index=False, startrow=2)
            print("\n✅ 성별/연령 보고서가 저장되었습니다:")
            print(f"📁 성별 리포트: {gender_path.resolve()}")
            print(f"📁 연령 리포트: {age_path.resolve()}")


def interactive_mode_my(config: ConfigParser):
    customer_ids_val = config.get("google-ads", "customer_ids", fallback="")
    if customer_ids_val == "":
        print("config.ini 의 google-ads 섹션이 잘못되었습니다. 샘플을 참조해주세요")
    customer_records = parse_customer_ids(customer_ids_val)
    customer_ids = [record["id"] for record in customer_records]
    print("사용 가능한 CUSTOMER IDS")

    # TODO: customer id 선택
    id = "USER SELECTED_ID"

    cam_df = get_active_campaigns(id, enabled_only=False)
    """
    cam_df 는 대충 이렇게 생겼다 (마크다운)
    |    |   campaign_id | campaign_name                                                                          | advertising_channel_type   | resource_name                              |
    |---:|--------------:|:---------------------------------------------------------------------------------------|:---------------------------|:-------------------------------------------|
    |  0 |   22783174972 | 250711_F1844_당신이 안면윤곽 재수술을 고민하는 이유 (사각턱, 광대, 턱끝 유형별 솔루션) | VIDEO                      | customers/4409347414/campaigns/22783174972 |
    |  1 |   22779378620 | 250711_F1844_쌍수,트임,눈 성형 고민? 아이디병원 랜선 상담소에 물어보세요!              | VIDEO                      | customers/4409347414/campaigns/22779378620 |
    """

    # TODO: 캠페인 나열하고 캠페인 id 선택
    cam_id = "USER SELECTED_CAM_ID"

    # TODO: 유저한테 뭐 할 건지 물어보기
    action = 1

    match action:
        case 1:
            # TODO: 게재지면 관련 쿼리를 묻는 섹션
            # TODO: 현재는 날짜만 물어보면된다
            start_date = "2025-07-01"
            end_date = "2025-07-20"
            df = get_youtube_video_report(id, cam_id, start_date=start_date, end_date=end_date)

            # TODO: 파일 저장
            # TODO: 기본값 파일명을 제시하기: {id}_{cam_id}_{end_date를 YYMMDD 로}
            fname = "..."
            df.to_excel(fname, index=False)

        case 2:
            # TODO: 잠재고객 결과 관련 쿼리를 묻는 섹션
            # TODO: 현재는 날짜만 물어보면된다
            gender_df, age_df = get_demographic_performance(id, cam_id, start_date=start_date, end_date=end_date)
            # TODO: 파일 저장
            # TODO: 기본값 파일명을 제시하기: {id}_{cam_id}_{end_date를 YYMMDD 로}
            fname = "..."
            gender_df.to_excel(fname, index=False)
            age_df.to_excel(fname, index=False)


def batch_mode(config: ConfigParser):
    pass


def check_required_files():
    missing = []

    # config.ini 체크
    config_path = Path("config.ini")
    if not config_path.exists():
        print("❌ config.ini 파일이 없습니다. 샘플을 참조해 주세요: config.ini.sample")
        missing.append("config.ini")

    # google-ads.yaml 체크
    ads_yaml_path = Path("google-ads.yaml")
    if not ads_yaml_path.exists():
        print("❌ google-ads.yaml 파일이 없습니다. 생성 방법은 공식 README를 참조해 주세요.")
        missing.append("google-ads.yaml")

    # 하나라도 없으면 종료
    if missing:
        print("\n🚫 필수 설정 파일이 누락되었습니다. 프로그램을 종료합니다.")
        input("아무 키나 누르면 종료됩니다.")
        sys.exit(1)


def main():
    config = load_config()
    do_interactive = config.getboolean("options", "interactive", fallback=True)
    if do_interactive:
        interactive_mode(config)
    else:
        batch_mode(config)


if __name__ == "__main__":
    try:
        main()
    except:
        traceback.print_exc()
        print("에러가 발생했습니다. 개발자에게 문의하세요.")
    finally:
        input("아무 키나 누르면 종료됩니다.")
