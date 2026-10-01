class SourceBlocked(Exception):
    """來源偵測到反爬（403/419/429 或假資料）。"""


class SourceSkipped(Exception):
    """來源未設定或本次不需執行。"""
