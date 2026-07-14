# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0

from openviking.parse.base import format_table_to_markdown


def test_format_table_to_markdown_escapes_cell_pipes():
    markdown = format_table_to_markdown([["a|b"]], has_header=False)

    assert markdown == "| a\\|b |"


def test_format_table_to_markdown_normalizes_cell_line_breaks():
    markdown = format_table_to_markdown(
        [["line1\r\nline2", "line3\rline4", "line5\nline6"]],
        has_header=False,
    )

    assert markdown == "| line1<br>line2 | line3<br>line4 | line5<br>line6 |"
