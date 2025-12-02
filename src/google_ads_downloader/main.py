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
from google_ads_downloader.upload import upload_json

EXCEL_MAX_ROWS = 1_048_576
VALID_FILE_TYPES = {"csv", "xlsx"}
BRAND_NAME_TO_ID = {
    "페브리즈": 1,
    "다우니": 2,
    "팬틴": 3,
    "헤드앤숄더": 5,
    "팸퍼스": 6,
}
AD_TYPE_ALIASES = {
    "nsk": "nonskip",
}


def get_preferred_file_type(config: ConfigParser) -> str:
    raw_value = config.get("options", "file_type", fallback="xlsx")
    normalized = raw_value.strip().lower()
    if normalized not in VALID_FILE_TYPES:
        print(f"⚠️ [options].file_type 값 '{raw_value}' 이(가) 유효하지 않아 기본값(xlsx)으로 저장합니다.")
        return "xlsx"
    return normalized


def save_dataframe(
    df,
    base_path: Path,
    preferred_format: str,
    *,
    startrow: int = 0,
    description: str = "보고서",
    enforce_excel_limit: bool = False,
):
    file_format = preferred_format if preferred_format in VALID_FILE_TYPES else "xlsx"
    row_count = 0 if df is None else len(df)
    allowed_rows = max(EXCEL_MAX_ROWS - startrow, 0)

    if enforce_excel_limit and file_format == "xlsx" and row_count > allowed_rows:
        file_format = "csv"
        print(f"⚠️ {description} 행 수 {row_count:,}가 XLSX 한도({allowed_rows:,} 행)를 초과하여 CSV로 저장합니다.")

    if file_format == "xlsx":
        final_path = Path(f"{base_path}.xlsx")
        df.to_excel(final_path, index=False, startrow=startrow)
    else:
        final_path = Path(f"{base_path}.csv")
        with open(final_path, "w", encoding="utf-8", newline="") as handle:
            for _ in range(startrow):
                handle.write("\n")
            df.to_csv(handle, index=False)

    return final_path


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

    file_type = get_preferred_file_type(config)

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
    date_tag = datetime.strptime(end_date, "%Y-%m-%d").strftime("%y%m%d")
    campaign_row = cam_df[cam_df["campaign_id"] == campaign_id].iloc[0]
    campaign_name_snippet = sanitize_filename(campaign_row["campaign_name"], max_length=None)

    customer_prefix = (
        f"{sanitize_filename(customer_alias, max_length=20)}_{customer_id}" if customer_alias else customer_id
    )
    base_fname = f"{date_tag}_{customer_prefix}_{campaign_id}_{campaign_name_snippet}"

    output_dir = Path("res/output")
    output_dir.mkdir(exist_ok=True, parents=True)

    match action:
        case 1:
            df = get_youtube_video_report(customer_id, campaign_id, start_date, end_date)
            df = clean_dataframe(df)
            # NOTE: 업로드 서버에서 첫 2줄 공백 여부를 유연하게 처리해야 합니다.
            report_path = save_dataframe(
                df,
                output_dir / f"{base_fname}_video",
                file_type,
                startrow=2,
                description="게재지면 보고서",
                enforce_excel_limit=True,
            )
            print(f"\n✅ 게재지면 보고서가 저장되었습니다:\n📁 {report_path.resolve()}")
        case 2:
            gender_df, age_df = get_demographic_performance(customer_id, campaign_id, start_date, end_date)
            gender_df = clean_dataframe(gender_df)
            age_df = clean_dataframe(age_df)
            # NOTE: 업로드 서버에서 첫 2줄 공백 여부를 유연하게 처리해야 합니다.
            gender_path = save_dataframe(
                gender_df,
                output_dir / f"{base_fname}_gender",
                file_type,
                startrow=2,
                description="성별 보고서",
                enforce_excel_limit=True,
            )
            age_path = save_dataframe(
                age_df,
                output_dir / f"{base_fname}_age",
                file_type,
                startrow=2,
                description="연령 보고서",
                enforce_excel_limit=True,
            )
            print("\n✅ 성별/연령 보고서가 저장되었습니다:")
            print(f"📁 성별 리포트: {gender_path.resolve()}")
            print(f"📁 연령 리포트: {age_path.resolve()}")


def batch_mode(config: ConfigParser):
    def normalize_ad_type(raw: str) -> str:
        if not raw:
            return ""
        stripped = raw.strip()
        return AD_TYPE_ALIASES.get(stripped.lower(), stripped)

    def parse_campaigns(raw: str) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            if "|" in item:
                cid, ad_type = item.split("|", 1)
                cid = cid.strip()
                ad_type = normalize_ad_type(ad_type)
            else:
                cid, ad_type = item, ""
            if cid:
                entries.append({"id": cid, "ad_type": ad_type})
        return entries

    def get_default_dates() -> tuple[str, str]:
        today = datetime.today()
        if today.day == 1:
            prev_last = today - timedelta(days=1)
            prev_first = prev_last.replace(day=1)
            return prev_first.strftime("%Y-%m-%d"), prev_last.strftime("%Y-%m-%d")
        start = today.replace(day=1)
        end = today - timedelta(days=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    customer_ids_val = config.get("google-ads", "customer_ids", fallback="")
    customer_records = parse_customer_ids(customer_ids_val)
    if not customer_records:
        print("❌ [google-ads].customer_ids 설정이 비었습니다. 작업을 종료합니다.")
        return

    output_dir = Path("res/output")
    output_dir.mkdir(exist_ok=True, parents=True)
    file_type = get_preferred_file_type(config)
    upload_url = config.get("options", "upload_url", fallback="").strip().rstrip("/")
    if not upload_url:
        print("⚠️ [options].upload_url 설정이 없어 업로드가 비활성화됩니다.")

    for record in customer_records:
        customer_id = record["id"]
        customer_alias = record["alias"]
        section = f"google-ads:{customer_id}"
        brand_name = customer_alias.strip() if customer_alias else ""
        brand_id = BRAND_NAME_TO_ID.get(brand_name)
        if upload_url and not brand_id:
            print(
                f"⚠️ 브랜드 ID 매핑을 찾을 수 없어 업로드를 건너뜁니다: customer={customer_id}, alias='{customer_alias}'"
            )

        # 캠페인ID|ad_type 목록
        raw_campaigns = config.get(section, "campaigns", fallback="")
        campaigns = parse_campaigns(raw_campaigns)
        if not campaigns:
            print(f"⚠️ {section}.campaigns 설정이 없거나 비어 있어 건너뜁니다.")
            continue

        # 날짜: 섹션에 지정 없으면 규칙 기반 기본값
        start_date = config.get(section, "start_date", fallback=None)
        end_date = config.get(section, "end_date", fallback=None)
        if not start_date or not end_date:
            start_date, end_date = get_default_dates()

        try:
            date_tag = datetime.strptime(end_date, "%Y-%m-%d").strftime("%y%m%d")
        except Exception:
            print(f"⚠️ 종료일 형식이 잘못되었습니다: {end_date} (YYYY-MM-DD 예상). 기본값으로 대체합니다.")
            start_date, end_date = get_default_dates()
            date_tag = datetime.strptime(end_date, "%Y-%m-%d").strftime("%y%m%d")

        customer_prefix = (
            f"{sanitize_filename(customer_alias, max_length=20)}_{customer_id}" if customer_alias else customer_id
        )

        for camp in campaigns:
            campaign_id = camp["id"]
            ad_type = camp.get("ad_type", "")
            try:
                base_fname = f"{date_tag}_{customer_prefix}_{campaign_id}"
                tag = sanitize_filename(ad_type, max_length=20) if ad_type else ""
                base_name = f"{base_fname}_{tag}" if tag else base_fname
                base_path = output_dir / base_name
                df = get_youtube_video_report(customer_id, campaign_id, start_date, end_date)
                row_count = 0 if df is None else len(df)

                # 로그 파일 생성 (동일 베이스명, 확장자만 .log)
                log_path = Path(f"{base_path}.log")
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                default_output_name = f"{base_name}.{'csv' if file_type == 'csv' else 'xlsx'}"

                if row_count == 0:
                    try:
                        with open(log_path, "w", encoding="utf-8") as f:
                            f.write(
                                "\n".join(
                                    [
                                        f"timestamp: {now_str}",
                                        f"customer_id: {customer_id}",
                                        f"campaign_id: {campaign_id}",
                                        f"ad_type: {ad_type}",
                                        f"date_range: {start_date} ~ {end_date}",
                                        f"rows: {row_count}",
                                        f"output: {default_output_name}",
                                    ]
                                )
                            )
                    except Exception as log_e:
                        print(f"⚠️ 로그 작성 실패: {log_path} | {log_e}")
                    print(
                        f"⚠️ 데이터 없음: {customer_id} / {campaign_id} ({start_date}~{end_date}). 로그만 생성됨: {log_path.name}"
                    )
                    continue

                df = clean_dataframe(df)
                # NOTE: 업로드 서버에서 첫 2줄 공백 여부를 유연하게 처리해야 합니다.
                report_path = save_dataframe(
                    df,
                    base_path,
                    file_type,
                    startrow=2,
                    description="게재지면 보고서",
                    enforce_excel_limit=True,
                )
                if upload_url and brand_id:
                    try:
                        upload_json(df, brand_id, ad_type, upload_url)
                        print(
                            f"☁️ 업로드 완료: brand_id={brand_id}, ad_type={ad_type or '-'} -> {upload_url}/upload-json"
                        )
                    except Exception as upload_error:
                        print(
                            f"⚠️ 업로드 실패: customer={customer_id}, campaign={campaign_id}, ad_type={ad_type} | {upload_error}"
                        )
                try:
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write(
                            "\n".join(
                                [
                                    f"timestamp: {now_str}",
                                    f"customer_id: {customer_id}",
                                    f"campaign_id: {campaign_id}",
                                    f"ad_type: {ad_type}",
                                    f"date_range: {start_date} ~ {end_date}",
                                    f"rows: {row_count}",
                                    f"output: {report_path.name}",
                                ]
                            )
                        )
                except Exception as log_e:
                    print(f"⚠️ 로그 작성 실패: {log_path} | {log_e}")
                print(f"✅ 저장됨: {report_path.resolve()} (로그: {log_path.name})")
            except Exception as e:
                print(f"❌ 실패: customer={customer_id}, campaign={campaign_id}, 기간={start_date}~{end_date} | {e}")


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
