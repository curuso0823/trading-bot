"""
utils/sectors.py
類股對照（A2 分散用）：把「會一起漲跌」的標的歸為同群，回測選股時限制同群同時進場檔數，
降低「3 檔全半導體齊跌」造成的系統性回撤。

回測 universe（b3 的 38 檔）用此硬表即可。實盤全市場掃描需動態來源 —— 之後可接
FinMind TaiwanStockInfo.industry_category 補上（get_sector 會 fallback "OTHER"）。
"""

# stock_id -> 類股群（強調共同波動，故半導體/代工/金融/航運各自成群）
SECTOR_MAP = {
    # 半導體
    "2330": "SEMI", "2454": "SEMI", "2303": "SEMI", "2379": "SEMI", "3034": "SEMI",
    "3711": "SEMI", "2337": "SEMI", "6415": "SEMI", "3008": "SEMI",
    # 電子代工 / PC / 伺服器
    "2317": "EMS", "2382": "EMS", "2357": "EMS", "2376": "EMS", "3231": "EMS",
    "4938": "EMS", "2356": "EMS", "2353": "EMS",
    # 電子零組件 / 電源
    "2308": "COMPONENT",
    # 金融
    "2881": "FIN", "2882": "FIN", "2891": "FIN", "2886": "FIN", "2884": "FIN",
    "2885": "FIN", "2892": "FIN", "5880": "FIN",
    # 塑化
    "1301": "PLASTIC", "1303": "PLASTIC", "1326": "PLASTIC",
    # 傳產原物料
    "1101": "CEMENT", "2002": "STEEL", "2207": "AUTO",
    # 航運（高相關）
    "2603": "SHIP", "2609": "SHIP", "2615": "SHIP",
    # 民生 / 電信
    "2412": "TELECOM", "2912": "RETAIL", "1216": "FOOD",
    # --- universe 擴充候選（分散電子+金融集中；2026-06 回測否決，僅留 GUI 實驗用）---
    "1513": "POWER", "1519": "POWER",     # 重電/綠能
    "2618": "AIRLINE",                     # 航空
    "2049": "MACHINE",                     # 工具機/自動化
    "1795": "BIOTECH",                     # 生技
    "3045": "TELECOM",                     # 電信（防禦）
    # --- AI 供應鏈強勢候選（2026-06 sector_scan 近3年 CAGR ≥ 0050；任務2+4 加單）---
    "2449": "SEMI", "8299": "SEMI", "2408": "SEMI",      # 京元電(測試)/群聯(NAND)/南亞科(DRAM)
    "6515": "SEMI", "5274": "SEMI",                       # 穎崴(測試介面)/信驊(BMC)
    "2383": "PCB", "2368": "PCB", "3037": "PCB",          # 台光電(CCL)/金像電/欣興(ABF)
    "2313": "PCB", "4958": "PCB",                         # 華通/臻鼎-KY
    "3017": "THERMAL",                                     # 奇鋐(散熱)
    "2345": "NETWORK",                                     # 智邦(交換器)
    "8210": "CHASSIS", "2059": "CHASSIS",                  # 勤誠(機殼)/川湖(導軌)
    "6669": "EMS",                                         # 緯穎(AI伺服器ODM)
}


def get_sector(stock_id: str) -> str:
    """回傳類股群；未知標的歸 'OTHER'（不受同群上限約束）。"""
    return SECTOR_MAP.get(str(stock_id), "OTHER")
