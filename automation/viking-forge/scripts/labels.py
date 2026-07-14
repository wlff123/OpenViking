from __future__ import annotations

import argparse
import subprocess


LABELS = {
    "agent:ready": ("2f81f7", "维护者批准自动修复"),
    "agent:claimed": ("0e8a16", "VikingForge 已接单"),
    "agent:pr-open": ("1d76db", "VikingForge 草稿 PR 已打开"),
    "agent:blocked": ("b60205", "自动流程需要人工处理"),
    "agent:triaged": ("5319e7", "当前修订版本已分诊"),
    "agent:analyze": ("fbca04", "状态面板请求只读分诊"),
    "agent:ignored": ("d4c5f9", "维护者决定暂不分析"),
    "agent:retriage": ("f9d0c4", "维护者请求重新分诊"),
    "needs:info": ("d876e3", "需要补充复现或验收信息"),
    "agent:human-only": ("000000", "仅限人工处理"),
    "agent:generated": ("bfdadc", "VikingForge 生成的 PR"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    for name, (color, description) in LABELS.items():
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                name,
                "--repo",
                args.repo,
                "--color",
                color,
                "--description",
                description,
                "--force",
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
