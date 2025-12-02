import pandas as pd
import requests


def upload_json(df: pd.DataFrame, brand_id: int, ad_type: str, base_url: str) -> None:
    payload = {
        "brand_id": brand_id,
        "ad_type": ad_type,
        "data": df.to_dict(orient="records"),
    }
    resp = requests.post(f"{base_url}/upload-json", json=payload, timeout=600)
    resp.raise_for_status()
