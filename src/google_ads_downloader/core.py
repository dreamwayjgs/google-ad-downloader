import pandas as pd
from google.ads.googleads.client import GoogleAdsClient


# 활성화된 캠페인 확인용
def get_active_campaigns(
    customer_id, yaml_path="google-ads.yaml", enabled_only: bool = False
):
    customer_id = customer_id.replace("-", "")

    client = GoogleAdsClient.load_from_storage(yaml_path)
    ga_service = client.get_service("GoogleAdsService")

    query = """
        SELECT 
            campaign.id,
            campaign.name,
            campaign.advertising_channel_type
        FROM campaign
    """
    if enabled_only:
        query += """
        WHERE campaign.status = 'ENABLED'
    """

    query += """
        ORDER BY campaign.name
    """

    campaigns_data = []

    response = ga_service.search_stream(customer_id=customer_id, query=query)
    for batch in response:
        for row in batch.results:
            campaigns_data.append(
                {
                    "campaign_id": row.campaign.id,
                    "campaign_name": row.campaign.name,
                    "advertising_channel_type": row.campaign.advertising_channel_type.name,
                    "resource_name": row.campaign.resource_name,
                }
            )

    df = pd.DataFrame(campaigns_data)
    return df


def get_youtube_video_report(
    customer_id,
    campaign_id,
    start_date,
    end_date,
    yaml_path="google-ads.yaml",
):
    customer_id = customer_id.replace("-", "")
    client = GoogleAdsClient.load_from_storage(yaml_path)
    ga_service = client.get_service("GoogleAdsService")

    channel_query = f"""
        SELECT 
            group_placement_view.placement,
            group_placement_view.display_name,
            group_placement_view.target_url,
            metrics.impressions
        FROM group_placement_view
        WHERE campaign.id = {campaign_id}
            AND segments.date BETWEEN '{start_date}' AND '{end_date}'
            AND metrics.impressions > 0
        ORDER BY metrics.impressions DESC
    """
    channel_rows = []
    campaign_name = ""

    response = ga_service.search_stream(customer_id=customer_id, query=channel_query)
    for batch in response:
        for row in batch.results:
            if not campaign_name:
                campaign_name = row.campaign.name

            channel_rows.append(
                {
                    "channel_url": getattr(row.group_placement_view, "target_url", None),
                    "Placement (group)": row.group_placement_view.display_name or "N/A",
                    "Placement (group) url": getattr(
                        row.group_placement_view, "target_url", None
                    ),
                }
            )

    if not channel_rows:
        print("⚠️ 캠페인 게재지면 데이터가 없습니다.")
        return pd.DataFrame()

    channel_data = pd.DataFrame(channel_rows)

    query = f"""
        SELECT 
            campaign.id,
            campaign.name,
            ad_group.id,
            ad_group.name,
            detail_placement_view.placement_type,
            detail_placement_view.placement,
            detail_placement_view.group_placement_target_url,
            detail_placement_view.display_name,
            detail_placement_view.target_url,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc,
            metrics.video_views,
            metrics.video_view_rate
        FROM detail_placement_view
        WHERE campaign.id = {campaign_id}
            AND segments.date BETWEEN '{start_date}' AND '{end_date}'
            AND metrics.impressions > 0
        ORDER BY metrics.impressions DESC
    """
    response = ga_service.search_stream(customer_id=customer_id, query=query)

    placements = []
    campaign_name = ""

    for batch in response:
        for row in batch.results:
            if not campaign_name:
                campaign_name = row.campaign.name

            placement_data = {
                # "campaign_id": row.campaign.id,
                # "campaign_name": row.campaign.name,
                # "ad_group_id": row.ad_group.id,
                # "ad_group_name": row.ad_group.name,
                # "placement_type": row.detail_placement_view.placement_type.name,
                "channel_url": row.detail_placement_view.group_placement_target_url,
                "Placement (detail) url": (
                    getattr(row.detail_placement_view, "target_url", None)
                    or row.detail_placement_view.placement
                ),
                "Placement (detail)": row.detail_placement_view.display_name or "N/A",
                "Impr.": row.metrics.impressions,
                "Cost": row.metrics.cost_micros / 1000000,
                # "Clicks": row.metrics.clicks,
                # "Conversions": row.metrics.conversions,
                # "CTR": row.metrics.ctr,
                # "Avg. CPC": row.metrics.average_cpc / 1000000,
                # "Video views": row.metrics.video_views,
                # "Video view rate": row.metrics.video_view_rate,
                # "Conversion rate": (
                #     (row.metrics.conversions / row.metrics.clicks * 100)
                #     if row.metrics.clicks > 0
                #     else 0
                # ),
            }
            placements.append(placement_data)

    if not placements:
        print("⚠️ 조회된 개별 게재위치가 없습니다.")
        return pd.DataFrame()

    df = pd.DataFrame(placements)
    df = pd.merge(df, channel_data, on="channel_url", how="left")

    df["Placement (group)"].fillna("N/A", inplace=True)
    df["Placement (group) url"].fillna(df["channel_url"], inplace=True)
    df = df.drop(columns=["channel_url"])

    df = df[
        [
            "Placement (group)",
            "Placement (group) url",
            "Placement (detail)",
            "Placement (detail) url",
            "Impr.",
            "Cost",
        ]
    ]

    print(f"캠페인: {campaign_name} (ID: {campaign_id})")
    print(f"총 {len(placements)}개의 개별 게재위치")

    return df


def get_demographic_performance(
    customer_id,
    campaign_id,
    start_date,
    end_date,
    yaml_path="google-ads.yaml",
):
    customer_id = customer_id.replace("-", "")
    client = GoogleAdsClient.load_from_storage(yaml_path)
    ga_service = client.get_service("GoogleAdsService")

    gender_query = f"""
        SELECT 
            campaign.id,
            campaign.name,
            ad_group_criterion.gender.type,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc
        FROM gender_view
        WHERE campaign.id = {campaign_id}
          AND segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND metrics.impressions > 0
    """

    age_query = f"""
        SELECT 
            campaign.id,
            campaign.name,
            ad_group_criterion.age_range.type,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc
        FROM age_range_view
        WHERE campaign.id = {campaign_id}
          AND segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND metrics.impressions > 0
    """

    gender_response = ga_service.search_stream(
        customer_id=customer_id, query=gender_query
    )
    age_response = ga_service.search_stream(customer_id=customer_id, query=age_query)

    gender_data = []
    age_data = []
    campaign_name = ""

    for batch in gender_response:
        for row in batch.results:
            if not campaign_name:
                campaign_name = row.campaign.name

            gender_data.append(
                {
                    "gender": row.ad_group_criterion.gender.type.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": row.metrics.cost_micros / 1000000,
                    "conversions": row.metrics.conversions,
                    "ctr": row.metrics.ctr,
                    "avg_cpc": row.metrics.average_cpc / 1000000,
                }
            )

    for batch in age_response:
        for row in batch.results:
            if not campaign_name:
                campaign_name = row.campaign.name

            age_data.append(
                {
                    "age_range": row.ad_group_criterion.age_range.type.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost": row.metrics.cost_micros / 1000000,
                    "conversions": row.metrics.conversions,
                    "ctr": row.metrics.ctr,
                    "avg_cpc": row.metrics.average_cpc / 1000000,
                }
            )

    gender_df = pd.DataFrame(gender_data)
    age_df = pd.DataFrame(age_data)

    return gender_df, age_df
