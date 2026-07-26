"""契约 CLI 模块入口

使用方式：
    python -m pycoder.contracts check
    python -m pycoder.contracts check --layer D
    python -m pycoder.contracts list
"""

from __future__ import annotations

import sys

from pycoder.contracts.checker import main as check_main


def main() -> int:
    """CLI 主入口"""
    if len(sys.argv) < 2:
        print("用法：python -m pycoder.contracts <command>")
        print("命令：")
        print("  check    检查所有模块契约合规性")
        print("  list     列出所有已声明的模块合同")
        return 1

    command = sys.argv[1]

    if command == "check":
        return check_main()
    elif command == "list":
        from pycoder.contracts.base import all_contracts

        contracts = all_contracts()
        print(f"已声明 {len(contracts)} 个模块合同：\n")
        for c in contracts:
            print(f"  [{c.layer}] {c.name}")
            if c.dependencies:
                print(f"        依赖: {', '.join(c.dependencies)}")
            if c.capabilities:
                print(f"        能力: {', '.join(c.capabilities)}")
            if c.invariants:
                for inv in c.invariants:
                    print(f"        不变式: {inv}")
            print()
        return 0
    else:
        print(f"未知命令：{command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
