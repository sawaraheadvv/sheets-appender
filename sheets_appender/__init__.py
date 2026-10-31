"""列の所有権を分けた表を Google スプレッドシートで維持する共通ライブラリ。

左側を機械が持ち、右側を人が持つ。機械は追記と自分の列の更新だけを行い、
**人が書いた列には絶対に触らない。行の移動・削除・並べ替えもしない。**

    from sheets_appender import Sheet, SheetSpec

    SPEC = SheetSpec(
        machine_columns=["ID", "名前", "登録日"],
        human_columns=["ステータス", "メモ"],
        hidden_columns=["ID"],
        dropdowns={"ステータス": ["未着手", "進行中", "完了"]},
    )

    sheet = Sheet(SPEC, spreadsheet_id)        # 既定は読み取り専用
    sheet.existing_keys()                      # A列のキーを集める

    sheet = Sheet(SPEC, spreadsheet_id, writable=True)
    sheet.ensure_tabs(["2026-10"])
    sheet.append_many({"2026-10": [{"ID": "1", "名前": "..."}]})
    sheet.apply_layout(["2026-10"])
"""

from .client import (
    KEY_ENV,
    KEY_FILE_ENV,
    SCOPES,
    ReadOnlyError,
    Sheet,
    SheetError,
    TabNotFoundError,
    execute,
    load_credentials,
)
from .spec import (
    DEFAULT_PALETTE,
    DEFAULT_PROTECTION_NOTE,
    Palette,
    SheetSpec,
)
from . import layout

__version__ = "1.0.0"

__all__ = [
    "DEFAULT_PALETTE",
    "DEFAULT_PROTECTION_NOTE",
    "KEY_ENV",
    "KEY_FILE_ENV",
    "Palette",
    "ReadOnlyError",
    "SCOPES",
    "Sheet",
    "SheetError",
    "SheetSpec",
    "TabNotFoundError",
    "execute",
    "layout",
    "load_credentials",
    "__version__",
]
