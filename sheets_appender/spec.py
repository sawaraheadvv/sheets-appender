"""シートの形を宣言する。利用側が作って `Sheet` に渡す。

このライブラリは**列の所有権を分けた表**を Google スプレッドシートで維持するためのもの。
左側を機械が持ち、右側を人が持つ。機械は人の列に絶対に書き込まない。

列名・色・タブ名の除外・プルダウンの中身は、すべてここから渡す。
ライブラリ側に既定値を持つのは色と保護の説明文だけで、どちらも差し替えられる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Optional


@dataclass(frozen=True)
class Palette:
    """列の所有権を色で示す。

    保護だけだと「押してみるまで分からない」ので、触ってよい場所が
    見た目で分かるようにする。
    """

    machine_header_bg: dict = field(
        default_factory=lambda: {"red": 0.925, "green": 0.937, "blue": 0.945}
    )
    machine_header_fg: dict = field(
        default_factory=lambda: {"red": 0.30, "green": 0.34, "blue": 0.37}
    )
    machine_body_bg: dict = field(
        default_factory=lambda: {"red": 1.0, "green": 1.0, "blue": 1.0}
    )
    human_header_bg: dict = field(
        default_factory=lambda: {"red": 1.0, "green": 0.878, "blue": 0.698}
    )
    human_header_fg: dict = field(
        default_factory=lambda: {"red": 0.60, "green": 0.32, "blue": 0.0}
    )
    human_body_bg: dict = field(
        default_factory=lambda: {"red": 1.0, "green": 0.988, "blue": 0.945}
    )


DEFAULT_PALETTE = Palette()

# 保護範囲につける説明。シートのUIに表示される
DEFAULT_PROTECTION_NOTE = "自動更新される列。手で編集しない"


@dataclass(frozen=True)
class SheetSpec:
    """1つのシートの列構成と見た目。

    必須なのは列の並びだけ。残りはすべて任意で、既定のまま使える。

        SheetSpec(
            machine_columns=["ID", "名前", "登録日"],
            human_columns=["ステータス", "メモ"],
            hidden_columns=["ID"],
            dropdowns={"ステータス": ["未着手", "進行中", "完了"]},
        )
    """

    # 機械が書く列。**A列が行の一意キー**（重複判定に使う）
    machine_columns: List[str]
    # 人が書く列。機械は `initial_values` に挙げたものを除いて一切触らない
    human_columns: List[str] = field(default_factory=list)
    # 人が見る必要のない列は隠す。データとしては残す
    hidden_columns: List[str] = field(default_factory=list)
    # 列幅（ピクセル）。指定がないものは既定のまま
    column_widths: Dict[str, int] = field(default_factory=dict)
    # プルダウンにする列と、その選択肢。表記ゆれを防ぐ
    dropdowns: Dict[str, List[str]] = field(default_factory=dict)
    # 行を**新規作成するときだけ**機械が入れる値。
    #
    # 「機械は人の列に触らない」の例外に見えるが、書くのは行の新規作成時のみ。
    # 追記は必ず末尾の空行から始まるので、人が入力済みの行に上書きすることはない。
    # 既存行の値を機械が更新することは一切ない。
    initial_values: Dict[str, str] = field(default_factory=dict)
    # データが入っていないタブの名前（集計タブ・README など）。
    #
    # **A列にキーが入るタブを増やすときは、ここに足してはいけない。**
    # ここに入れると走査されず、その行が「未出力」扱いで再度出力される。
    skip_tabs: FrozenSet[str] = frozenset()
    palette: Palette = field(default_factory=Palette)
    protection_note: str = DEFAULT_PROTECTION_NOTE
    # このシートだけの書式を足すフック。`(spec, tab_id) -> list[dict]`。
    # Sheets API のリクエストをそのまま返す。条件付き書式などに使う
    extra_layout: Optional[Callable[["SheetSpec", int], List[dict]]] = None

    @property
    def header(self) -> List[str]:
        return list(self.machine_columns) + list(self.human_columns)

    @property
    def written_columns(self) -> List[str]:
        """機械が実際に書き込む列。機械の列＋初期値を入れる列だけ。

        ここから右は空のまま残す。空文字を書き込むと、後から人が入力した値を
        消しにいくことになる。
        """
        return list(self.machine_columns) + list(self.initial_values)

    @property
    def last_column(self) -> str:
        """ヘッダ最後の列のA1記法。Z列（26列）を超えるシートは未対応。"""
        if len(self.header) > 26:
            raise ValueError(
                f"列が26を超えています（{len(self.header)}列）。"
                "AA以降のA1記法に未対応です"
            )
        return chr(ord("A") + len(self.header) - 1)

    def index(self, name: str) -> int:
        return self.header.index(name)

    def __post_init__(self) -> None:
        if not self.machine_columns:
            raise ValueError("machine_columns が空です")
        header = self.header
        dupes = {c for c in header if header.count(c) > 1}
        if dupes:
            raise ValueError(f"列名が重複しています: {sorted(dupes)}")
        for group, names in (
            ("hidden_columns", self.hidden_columns),
            ("column_widths", list(self.column_widths)),
            ("dropdowns", list(self.dropdowns)),
            ("initial_values", list(self.initial_values)),
        ):
            unknown = [n for n in names if n not in header]
            if unknown:
                raise ValueError(f"{group} に無い列が指定されています: {unknown}")
        # 初期値を入れる列は、機械の列のすぐ右に連続している必要がある。
        # 飛んだ位置を指定すると、間の列を空文字で上書きしてしまう
        expected = self.human_columns[: len(self.initial_values)]
        if list(self.initial_values) != expected:
            raise ValueError(
                "initial_values は human_columns の先頭から連続している必要があります"
                f"（指定 {list(self.initial_values)} / 期待 {expected}）"
            )
