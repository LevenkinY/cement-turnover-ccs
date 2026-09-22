"""
Build plant-level location_tier classification for v4.

Outputs:
    - data/model_input/plants/plant_location_tier.csv

v4 design (REALISM_STRUCTURE_UPDATE.md §2.3 M2'):
    TSR upper bounds by location_tier:
      metro   (0.45)  — updated to config_v5.py TIER_TSR_CEILING
      city    (0.30)
      county  (0.15)
      remote  (0.08)

Classification rationale:
  - metro:  provincial capitals + direct-administered municipalities + top-10 city GDP
  - city:   prefecture-level cities, autonomous prefectures, league cities
  - county: counties, autonomous counties, autonomous prefectures (no "市" suffix)
  - remote: plateau border regions (Tibet, Qinghai, Altay/Xinjiang border)

Classification approach:
  1. Known explicit map for major cities and provincial capitals
  2. Pattern matching on city name suffix + known administrative hierarchy
  3. Province-level fallback for remaining provinces
  4. Optional: lat/lon density check for ambiguous cases

No new model code written to src/ — this is a data preparation script.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_INPUT = PROJECT_ROOT / "data" / "model_input"
PLANTS_OUTPUT = DATA_INPUT / "plants"

PLANT_XLSX = DATA_INPUT / "plants" / "plant_data.xlsx"


# ---------------------------------------------------------------------------
# Tier classification helpers
# ---------------------------------------------------------------------------

# Known explicit tier assignments: city_name → tier
# Covers provincial capitals, direct-administered municipalities, top GDP cities
EXPLICIT_TIER_MAP = {
    # Provincial capitals → metro
    "北京": "metro", "上海": "metro", "天津": "metro", "重庆": "metro",
    "广州": "metro", "深圳": "metro",
    "杭州": "metro", "南京": "metro", "武汉": "metro", "成都": "metro",
    "西安": "metro", "苏州": "metro", "长沙": "metro", "郑州": "metro",
    "沈阳": "metro", "大连": "metro", "青岛": "metro", "济南": "metro",
    "福州": "metro", "厦门": "metro", "昆明": "metro", "兰州": "metro",
    "石家庄": "metro", "太原": "metro", "合肥": "metro", "南昌": "metro",
    "贵阳": "metro", "南宁": "metro", "海口": "metro", "拉萨": "metro",
    "乌鲁木齐": "metro", "呼和浩特": "metro", "银川": "metro", "西宁": "metro",
    # Capital variants with suffix
    "石家庄市": "metro", "太原市": "metro", "杭州市": "metro", "合肥市": "metro",
    "福州市": "metro", "南昌市": "metro", "济南市": "metro", "郑州市": "metro",
    "武汉市": "metro", "长沙市": "metro", "广州市": "metro", "南宁市": "metro",
    "海口市": "metro", "重庆市": "metro", "成都市": "metro", "贵阳市": "metro",
    "昆明市": "metro", "拉萨市": "metro", "西安市": "metro", "兰州市": "metro",
    "西宁市": "metro", "银川市": "metro", "乌鲁木齐市": "metro", "呼和浩特市": "metro",
    "沈阳市": "metro", "大连市": "metro", "长春市": "metro", "哈尔滨市": "metro",
    "南京市": "metro", "杭州市": "metro", "福州市": "metro", "青岛市": "metro",
    "深圳市": "metro", "厦门市": "metro",
    # Bare city names (no 市 suffix) — major prefecture capitals
    "石家庄": "metro", "太原": "metro", "合肥": "metro", "南昌": "metro",
    "济南": "metro", "郑州": "metro", "武汉": "metro", "长沙": "metro",
    "广州": "metro", "南宁": "metro", "海口": "metro", "重庆": "metro",
    "成都": "metro", "贵阳": "metro", "昆明": "metro", "拉萨": "metro",
    "西安": "metro", "兰州": "metro", "西宁": "metro", "银川": "metro",
    "乌鲁木齐": "metro", "呼和浩特": "metro", "沈阳": "metro", "大连": "metro",
    "长春": "metro", "哈尔滨": "metro", "南京": "metro", "杭州": "metro",
    "福州": "metro", "青岛": "metro", "深圳": "metro", "厦门": "metro",
    # Jiangsu prefecture capitals → city (bare + suffixed)
    "无锡": "city", "无锡市": "city", "常州": "city", "常州市": "city",
    "苏州": "city", "苏州市": "city", "南通": "city", "南通市": "city",
    "徐州": "city", "徐州市": "city", "连云港": "city", "连云港市": "city",
    "淮安": "city", "淮安市": "city", "盐城": "city", "盐城市": "city",
    "扬州": "city", "扬州市": "city", "镇江": "city", "镇江市": "city",
    "泰州": "city", "泰州市": "city", "宿迁": "city", "宿迁市": "city",
    # Zhejiang prefecture cities
    "宁波": "city", "宁波市": "city", "温州": "city", "温州市": "city",
    "嘉兴": "city", "嘉兴市": "city", "湖州": "city", "湖州市": "city",
    "绍兴": "city", "绍兴市": "city", "金华": "city", "金华市": "city",
    "衢州": "city", "衢州市": "city", "舟山": "city", "舟山市": "city",
    "台州": "city", "台州市": "city", "丽水": "city", "丽水市": "city",
    # Shandong prefecture cities
    "烟台": "city", "烟台市": "city", "潍坊": "city", "潍坊市": "city",
    "济宁": "city", "济宁市": "city", "泰安": "city", "泰安市": "city",
    "威海": "city", "威海市": "city", "日照": "city", "日照市": "city",
    "临沂": "city", "临沂市": "city", "德州": "city", "德州市": "city",
    "聊城": "city", "聊城市": "city", "滨州": "city", "滨州市": "city",
    "菏泽": "city", "菏泽市": "city", "枣庄": "city", "枣庄市": "city",
    "淄博": "city", "淄博市": "city", "东营": "city", "东营市": "city",
    # Hebei prefecture cities
    "唐山": "city", "唐山市": "city", "秦皇岛": "city", "秦皇岛市": "city",
    "邯郸": "city", "邯郸市": "city", "邢台": "city", "邢台市": "city",
    "保定": "city", "保定市": "city", "张家口": "city", "张家口市": "city",
    "承德": "city", "承德市": "city", "沧州": "city", "沧州市": "city",
    "廊坊": "city", "廊坊市": "city", "衡水": "city", "衡水市": "city",
    # Shanxi prefecture cities
    "大同": "city", "大同市": "city", "阳泉": "city", "阳泉市": "city",
    "长治": "city", "长治市": "city", "晋城": "city", "晋城市": "city",
    "朔州": "city", "朔州市": "city", "晋中": "city", "晋中市": "city",
    "运城": "city", "运城市": "city", "忻州": "city", "忻州市": "city",
    "临汾": "city", "临汾市": "city", "吕梁": "city", "吕梁市": "city",
    # Inner Mongolia prefecture-level (city-tier for industrial centers)
    "包头": "city", "包头市": "city",
    "鄂尔多斯": "city", "鄂尔多斯市": "city",
    "呼和浩特": "city", "呼和浩特市": "city",
    "呼伦贝尔": "city", "呼伦贝尔市": "city",
    "赤峰": "city", "赤峰市": "city",
    "通辽": "city", "通辽市": "city",
    "乌海": "city", "乌海市": "city",
    "乌兰察布": "city", "乌兰察布市": "city",
    "巴彦淖尔": "county", "巴彦淖尔市": "county",
    "锡林郭勒盟": "remote",
    "兴安盟": "remote",
    "阿拉善盟": "remote",
    # Liaoning prefecture cities
    "鞍山": "city", "鞍山市": "city", "抚顺": "city", "抚顺市": "city",
    "本溪": "city", "本溪市": "city", "丹东": "city", "丹东市": "city",
    "锦州": "city", "锦州市": "city", "营口": "city", "营口市": "city",
    "阜新": "city", "阜新市": "city", "辽阳": "city", "辽阳市": "city",
    "盘锦": "city", "盘锦市": "city", "铁岭": "city", "铁岭市": "city",
    "朝阳": "city", "朝阳市": "city", "葫芦岛": "city", "葫芦岛市": "city",
    # Jilin prefecture cities
    "吉林": "city", "吉林市": "city", "四平": "city", "四平市": "city",
    "辽源": "city", "辽源市": "city", "通化": "city", "通化市": "city",
    "白山": "city", "白山市": "city", "松原": "city", "松原市": "city",
    "白城": "city", "白城市": "city",
    # Heilongjiang prefecture cities
    "齐齐哈尔": "city", "齐齐哈尔市": "city", "鸡西": "city", "鸡西市": "city",
    "鹤岗": "city", "鹤岗市": "city", "双鸭山": "city", "双鸭山市": "city",
    "大庆": "city", "大庆市": "city", "伊春": "city", "伊春市": "city",
    "佳木斯": "city", "佳木斯市": "city", "七台河": "city", "七台河市": "city",
    "牡丹江": "city", "牡丹江市": "city", "黑河": "city", "黑河市": "city",
    "绥化": "city", "绥化市": "city",
    # Anhui prefecture cities
    "芜湖": "city", "芜湖市": "city", "蚌埠": "city", "蚌埠市": "city",
    "淮南": "city", "淮南市": "city", "马鞍山": "city", "马鞍山市": "city",
    "淮北": "city", "淮北市": "city", "铜陵": "city", "铜陵市": "city",
    "安庆": "city", "安庆市": "city", "黄山": "city", "黄山市": "city",
    "滁州": "city", "滁州市": "city", "阜阳": "city", "阜阳市": "city",
    "宿州": "city", "宿州市": "city", "六安": "city", "六安市": "city",
    "亳州": "city", "亳州市": "city", "池州": "city", "池州市": "city",
    "宣城": "city", "宣城市": "city",
    # Fujian prefecture cities
    "莆田": "city", "莆田市": "city", "三明": "city", "三明市": "city",
    "泉州": "city", "泉州市": "city", "漳州": "city", "漳州市": "city",
    "南平": "city", "南平市": "city", "龙岩": "city", "龙岩市": "city",
    "宁德": "city", "宁德市": "city",
    # Jiangxi prefecture cities
    "景德镇": "city", "景德镇市": "city", "萍乡": "city", "萍乡市": "city",
    "九江": "city", "九江市": "city", "新余": "city", "新余市": "city",
    "鹰潭": "city", "鹰潭市": "city", "赣州": "city", "赣州市": "city",
    "吉安": "city", "吉安市": "city", "宜春": "city", "宜春市": "city",
    "抚州": "city", "抚州市": "city", "上饶": "city", "上饶市": "city",
    # Shandong county-level cities (some prefecture-level)
    "滕州": "city", "龙口": "city", "胶州": "city", "即墨": "city",
    "平度": "city", "莱西": "city", "寿光": "city", "诸城": "city",
    "青州": "city", "高密": "city", "曲阜": "city", "肥城": "city",
    "新泰": "city", "荣成": "city", "乳山": "city", "文登": "city",
    "临清": "city", "乐陵": "city", "禹城": "city",
    # Henan prefecture cities
    "开封": "city", "开封市": "city", "平顶山": "city", "平顶山市": "city",
    "安阳": "city", "安阳市": "city", "鹤壁": "city", "鹤壁市": "city",
    "新乡": "city", "新乡市": "city", "焦作": "city", "焦作市": "city",
    "濮阳": "city", "濮阳市": "city", "许昌": "city", "许昌市": "city",
    "漯河": "city", "漯河市": "city", "三门峡": "city", "三门峡市": "city",
    "南阳": "city", "南阳市": "city", "商丘": "city", "商丘市": "city",
    "信阳": "city", "信阳市": "city", "周口": "city", "周口市": "city",
    "驻马店": "city", "驻马店市": "city",
    # Hubei prefecture cities
    "黄石": "city", "黄石市": "city", "十堰": "city", "十堰市": "city",
    "宜昌": "city", "宜昌市": "city", "襄阳": "city", "襄阳市": "city",
    "鄂州": "city", "鄂州市": "city", "荆门": "city", "荆门市": "city",
    "孝感": "city", "孝感市": "city", "荆州": "city", "荆州市": "city",
    "黄冈": "city", "黄冈市": "city", "咸宁": "city", "咸宁市": "city",
    "随州": "city", "随州市": "city", "恩施": "city", "恩施市": "city",
    # Hunan prefecture cities
    "株洲": "city", "株洲市": "city", "湘潭": "city", "湘潭市": "city",
    "衡阳": "city", "衡阳市": "city", "邵阳": "city", "邵阳市": "city",
    "岳阳": "city", "岳阳市": "city", "常德": "city", "常德市": "city",
    "张家界": "city", "张家界市": "city", "益阳": "city", "益阳市": "city",
    "郴州": "city", "郴州市": "city", "永州": "city", "永州市": "city",
    "怀化": "city", "怀化市": "city", "娄底": "city", "娄底市": "city",
    "吉首": "city",
    # Guangdong prefecture cities
    "韶关": "city", "韶关市": "city", "汕头": "city", "汕头市": "city",
    "佛山": "city", "佛山市": "city", "江门": "city", "江门市": "city",
    "湛江": "city", "湛江市": "city", "茂名": "city", "茂名市": "city",
    "肇庆": "city", "肇庆市": "city", "惠州": "city", "惠州市": "city",
    "梅州": "city", "梅州市": "city", "汕尾": "city", "汕尾市": "city",
    "河源": "city", "河源市": "city", "阳江": "city", "阳江市": "city",
    "清远": "city", "清远市": "city", "潮州": "city", "潮州市": "city",
    "揭阳": "city", "揭阳市": "city", "云浮": "city", "云浮市": "city",
    "东莞": "city", "佛山市": "city", "中山": "city", "珠海": "city",
    # Guangxi prefecture cities
    "柳州": "city", "柳州市": "city", "桂林": "city", "桂林市": "city",
    "梧州": "city", "梧州市": "city", "北海": "city", "北海市": "city",
    "防城港": "city", "防城港市": "city", "钦州": "city", "钦州市": "city",
    "贵港": "city", "贵港市": "city", "玉林": "city", "玉林市": "city",
    "百色": "city", "百色市": "city", "贺州": "city", "贺州市": "city",
    "河池": "city", "河池市": "city", "来宾": "city", "来宾市": "city",
    "崇左": "city", "崇左市": "city",
    # Sichuan prefecture cities
    "自贡": "city", "自贡市": "city", "攀枝花": "city", "攀枝花市": "city",
    "泸州": "city", "泸州市": "city", "德阳": "city", "德阳市": "city",
    "绵阳": "city", "绵阳市": "city", "广元": "city", "广元市": "city",
    "遂宁": "city", "遂宁市": "city", "内江": "city", "内江市": "city",
    "乐山": "city", "乐山市": "city", "南充": "city", "南充市": "city",
    "眉山": "city", "眉山市": "city", "宜宾": "city", "宜宾市": "city",
    "广安": "city", "广安市": "city", "达州": "city", "达州市": "city",
    "雅安": "city", "雅安市": "city", "巴中": "city", "巴中市": "city",
    "资阳": "city", "资阳市": "city", "康定": "city", "马尔康": "city",
    "西昌": "city",
    # Guizhou prefecture cities
    "六盘水": "city", "六盘水市": "city", "遵义": "city", "遵义市": "city",
    "安顺": "city", "安顺市": "city", "毕节": "city", "毕节市": "city",
    "铜仁": "city", "铜仁市": "city", "兴义": "city", "都匀": "city",
    "凯里": "city", "福泉": "city",
    # Yunnan prefecture cities
    "曲靖": "city", "曲靖市": "city", "玉溪": "city", "玉溪市": "city",
    "保山": "city", "保山市": "city", "昭通": "city", "昭通市": "city",
    "丽江": "city", "丽江市": "city", "普洱": "city", "普洱市": "city",
    "临沧": "city", "临沧市": "city", "楚雄": "city", "个旧": "city",
    "开远": "city", "蒙自": "city", "景洪": "city", "大理": "city",
    "瑞丽": "city",
    # Shaanxi prefecture cities
    "铜川": "city", "铜川市": "city", "宝鸡": "city", "宝鸡市": "city",
    "咸阳": "city", "咸阳市": "city", "渭南": "city", "渭南市": "city",
    "延安": "city", "延安市": "city", "汉中": "city", "汉中市": "city",
    "榆林": "city", "榆林市": "city", "安康": "city", "安康市": "city",
    "商洛": "city", "商洛市": "city",
    # Gansu prefecture cities
    "嘉峪关": "city", "嘉峪关市": "city", "金昌": "city", "金昌市": "city",
    "白银": "city", "白银市": "city", "天水": "city", "天水市": "city",
    "武威": "city", "武威市": "city", "张掖": "city", "张掖市": "city",
    "平凉": "city", "平凉市": "city", "酒泉": "city", "酒泉市": "city",
    "庆阳": "city", "庆阳市": "city", "定西": "city", "定西市": "city",
    "陇南": "city", "陇南市": "city", "临夏": "city", "合作": "city",
    # Qinghai prefecture cities
    "海东": "city", "海东市": "city", "格尔木": "city", "德令哈": "city",
    "玉树": "city",
    # Ningxia prefecture cities
    "石嘴山": "city", "石嘴山市": "city", "吴忠": "city", "吴忠市": "city",
    "固原": "city", "固原市": "city", "中卫": "city", "中卫市": "city",
    # Xinjiang prefecture cities
    "克拉玛依": "city", "克拉玛依市": "city", "吐鲁番": "city", "吐鲁番市": "city",
    "哈密": "city", "哈密市": "city", "昌吉": "city", "昌吉市": "city",
    "博乐": "city", "库尔勒": "city", "阿克苏": "city", "阿图什": "city",
    "喀什": "city", "喀什市": "city", "和田": "city", "奎屯": "city",
    "霍尔果斯": "city",
    # Tibet prefecture cities
    "昌都": "city", "日喀则": "city",
}

# City name suffixes that strongly indicate city-tier (prefecture-level city)
CITY_SUFFIXES = ["市"]
# County suffixes
COUNTY_SUFFIXES = ["县", "自治县", "旗", "林区"]
# Remote / plateau provinces (fallback to remote if no better signal)
REMOTE_PROVINCES = {"西藏", "青海", "新疆", "内蒙古"}

# Province-level fallback tier (used when city not explicitly mapped)
PROVINCE_FALLBACK_TIER = {
    "北京": "metro", "天津": "metro", "上海": "metro", "重庆": "metro",
    "广东": "city", "江苏": "city", "浙江": "city", "山东": "city",
    "河南": "city", "四川": "city", "湖北": "city", "湖南": "city",
    "河北": "county", "山西": "city", "辽宁": "city", "吉林": "county",
    "黑龙江": "county", "安徽": "county", "福建": "county", "江西": "county",
    "广西": "county", "海南": "county", "贵州": "county", "云南": "county",
    "陕西": "county", "甘肃": "county", "青海": "remote", "宁夏": "county",
    "内蒙古": "remote", "新疆": "remote", "西藏": "remote",
}


def normalize_city_name(city: str) -> str:
    """Strip whitespace, return as-is."""
    if pd.isna(city):
        return ""
    return str(city).strip()


def classify_city(city: str, province: str) -> str:
    """
    Classify a plant's location tier based on city name and province.

    Priority:
      1. EXPLICIT_TIER_MAP lookup (exact match)
      2. Strip common suffixes then lookup (handles bare names like "赣州" vs "赣州市")
      3. City suffix → city-tier (for explicitly named prefecture-levels)
      4. Province-level fallback

    Returns: "metro" | "city" | "county" | "remote"
    """
    city = normalize_city_name(city)
    if not city:
        return PROVINCE_FALLBACK_TIER.get(province, "county")

    # 1. Exact lookup
    if city in EXPLICIT_TIER_MAP:
        return EXPLICIT_TIER_MAP[city]

    # 2. Strip suffix then lookup (handles "赣州市" → "赣州")
    for suffix in ["市"]:
        if city.endswith(suffix):
            bare = city[:-1]
            if bare in EXPLICIT_TIER_MAP:
                return EXPLICIT_TIER_MAP[bare]
            break

    # 3. City suffix → city-tier (prefecture-level city)
    for suffix in CITY_SUFFIXES:
        if city.endswith(suffix):
            return "city"

    # 4. County suffix → county-tier
    for suffix in COUNTY_SUFFIXES:
        if city.endswith(suffix):
            return "county"

    # 5. Province fallback
    province_tier = PROVINCE_FALLBACK_TIER.get(province, "county")
    return province_tier


def main():
    print("=" * 60)
    print("  Plant Location Tier Builder (v4)")
    print("=" * 60)

    # --- load plants ---
    plants = pd.read_excel(PLANT_XLSX)
    required_cols = ["id", "province", "city"]
    missing = [c for c in required_cols if c not in plants.columns]
    if missing:
        print(f"ERROR: plant_data.xlsx missing columns: {missing}")
        sys.exit(1)

    plants = plants[["id", "province", "city"]].copy()
    plants["province"] = plants["province"].fillna("").astype(str)
    plants["city"] = plants["city"].fillna("").astype(str)

    print(f"\n  Total plants: {len(plants)}")

    # --- classify ---
    t0 = time.time()
    tiers = []
    for _, row in plants.iterrows():
        tier = classify_city(row["city"], row["province"])
        tiers.append(tier)

    df_out = pd.DataFrame({
        "plant_id": plants["id"],
        "location_tier": tiers,
    })

    # --- save ---
    PLANTS_OUTPUT.mkdir(parents=True, exist_ok=True)
    out_path = PLANTS_OUTPUT / "plant_location_tier.csv"
    df_out.to_csv(out_path, index=False)

    print(f"\n  Output: {out_path}")
    print(f"  Rows: {len(df_out)}")
    print(f"  Time: {time.time()-t0:.2f}s")

    # --- summary ---
    tier_counts = df_out["location_tier"].value_counts()
    print(f"\n  Tier distribution:")
    for tier in ["metro", "city", "county", "remote"]:
        n = tier_counts.get(tier, 0)
        pct = n / len(df_out) * 100
        print(f"    {tier:8s}: {n:5d} ({pct:5.1f}%)")

    # Spot check some plants
    print(f"\n  Sample plants:")
    sample = plants.sample(min(10, len(plants)), random_state=42)
    for _, row in sample.iterrows():
        tier = classify_city(row["city"], row["province"])
        print(f"    [{row['id']}] {row['province']}/{row['city'][:10]:10s} → {tier}")

    print("=" * 60)
    print("  Done.")


if __name__ == "__main__":
    main()
