"""SheetSpec の導出と、受け付けない形の検査。"""

import pytest

from sheets_appender import DEFAULT_PROTECTION_NOTE, Palette, SheetSpec


def test_header_is_machine_then_human(spec):
    assert spec.header == ["ID", "名前", "登録日", "ステータス", "担当", "メモ"]


def test_written_columns_stop_after_initial_values(spec):
    # 「担当」「メモ」は書かない。空文字で上書きすると人の入力を消すため
    assert spec.written_columns == ["ID", "名前", "登録日", "ステータス"]


def test_last_column(spec):
    assert spec.last_column == "F"


def test_index(spec):
    assert spec.index("ステータス") == 3


def test_defaults_are_filled():
    spec = SheetSpec(machine_columns=["ID"])
    assert spec.human_columns == []
    assert spec.skip_tabs == frozenset()
    assert spec.protection_note == DEFAULT_PROTECTION_NOTE
    assert spec.extra_layout is None
    assert spec.written_columns == ["ID"]


def test_palette_is_not_shared_between_specs():
    # 既定の Palette を共有すると、片方の色を変えたら両方変わってしまう
    a = SheetSpec(machine_columns=["ID"])
    b = SheetSpec(machine_columns=["ID"])
    assert a.palette is not b.palette


def test_palette_can_be_replaced():
    red = {"red": 1.0, "green": 0.0, "blue": 0.0}
    spec = SheetSpec(machine_columns=["ID"], palette=Palette(machine_header_bg=red))
    assert spec.palette.machine_header_bg == red


def test_machine_columns_cannot_be_empty():
    with pytest.raises(ValueError, match="machine_columns が空"):
        SheetSpec(machine_columns=[])


def test_duplicate_column_names_are_rejected():
    with pytest.raises(ValueError, match="重複"):
        SheetSpec(machine_columns=["ID", "名前"], human_columns=["名前"])


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"hidden_columns": ["無い列"]}, "hidden_columns"),
        ({"column_widths": {"無い列": 100}}, "column_widths"),
        ({"dropdowns": {"無い列": ["a"]}}, "dropdowns"),
        ({"initial_values": {"無い列": ""}}, "initial_values"),
    ],
)
def test_unknown_columns_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        SheetSpec(machine_columns=["ID"], human_columns=["メモ"], **kwargs)


def test_initial_values_must_be_a_prefix_of_human_columns():
    # 飛んだ位置を許すと、間の列を空文字で上書きしてしまう
    with pytest.raises(ValueError, match="連続"):
        SheetSpec(
            machine_columns=["ID"],
            human_columns=["ステータス", "メモ"],
            initial_values={"メモ": ""},
        )


def test_more_than_26_columns_is_rejected():
    spec = SheetSpec(machine_columns=[f"C{i}" for i in range(27)])
    with pytest.raises(ValueError, match="26"):
        spec.last_column
