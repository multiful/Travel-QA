"""JSON 파일 빠른 확인 유틸리티
=================================
사용법:
    python3 scripts/inspect_json.py data/_checkpoint.json
    python3 scripts/inspect_json.py data/_checkpoint.json --key seen_contentids
    python3 scripts/inspect_json.py phases/0-setup/cache_geo.json --sample 5
    python3 scripts/inspect_json.py data/_checkpoint.json --tree

옵션:
    --key   <path>   특정 키 경로만 출력 (예: response.body.items)
    --sample <N>     리스트/딕트의 처음 N개 샘플만 출력 (기본 3)
    --tree           구조(키 + 타입)만 트리 형태로 출력 (값 생략)
    --search <text>  값에서 텍스트 포함 항목 검색
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def get_path(data: Any, path: str) -> Any:
    """'a.b.0.c' 형태 경로로 dict/list 안으로 들어감."""
    cur = data
    if not path:
        return cur
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return f"<경로 오류: '{part}' (list 길이 {len(cur)})>"
        elif isinstance(cur, dict):
            if part not in cur:
                return f"<키 없음: '{part}' (사용 가능: {list(cur.keys())[:10]})>"
            cur = cur[part]
        else:
            return f"<탐색 불가: {type(cur).__name__}>"
    return cur


def describe(value: Any, max_chars: int = 100) -> str:
    """타입 + 길이 + 짧은 미리보기."""
    t = type(value).__name__
    if isinstance(value, (list, tuple)):
        return f"{t}(len={len(value)})"
    if isinstance(value, dict):
        return f"dict(keys={len(value)})"
    if isinstance(value, str):
        preview = value[:max_chars]
        return f"str(len={len(value)}) {preview!r}" + ("..." if len(value) > max_chars else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return f"{t} {value!r}"
    return f"{t} {str(value)[:max_chars]}"


def print_tree(data: Any, prefix: str = "", depth: int = 0, max_depth: int = 5) -> None:
    """구조만 트리로 출력 (값은 타입과 길이만)."""
    if depth > max_depth:
        print(f"{prefix}... (max_depth)")
        return
    if isinstance(data, dict):
        keys = list(data.keys())
        for i, k in enumerate(keys):
            is_last = i == len(keys) - 1
            marker = "└─ " if is_last else "├─ "
            v = data[k]
            print(f"{prefix}{marker}{k}: {describe(v, 40)}")
            if isinstance(v, (dict, list)) and v:
                child_prefix = prefix + ("   " if is_last else "│  ")
                print_tree(v, child_prefix, depth + 1, max_depth)
    elif isinstance(data, list):
        if not data:
            print(f"{prefix}(empty list)")
            return
        # 리스트는 첫 항목만 보여줌 (나머지는 …)
        print(f"{prefix}├─ [0]: {describe(data[0], 40)}")
        if isinstance(data[0], (dict, list)) and data[0]:
            print_tree(data[0], prefix + "│  ", depth + 1, max_depth)
        if len(data) > 1:
            print(f"{prefix}└─ ... (총 {len(data)}개)")


def search_in(data: Any, text: str, path: str = "") -> list[tuple[str, Any]]:
    """모든 값에서 text 포함 항목 찾기. 반환: [(경로, 값)]"""
    results = []
    if isinstance(data, dict):
        for k, v in data.items():
            new_path = f"{path}.{k}" if path else k
            if text.lower() in str(k).lower():
                results.append((new_path, v))
            results.extend(search_in(v, text, new_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{path}.{i}"
            results.extend(search_in(item, text, new_path))
    else:
        if text.lower() in str(data).lower():
            results.append((path, data))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="JSON 파일 빠른 확인")
    parser.add_argument("file", help="JSON 파일 경로")
    parser.add_argument("--key", default="", help="특정 키 경로 (예: a.b.0.c)")
    parser.add_argument("--sample", type=int, default=3, help="리스트/딕트 미리보기 개수")
    parser.add_argument("--tree", action="store_true", help="구조만 트리로 출력")
    parser.add_argument("--search", default="", help="값에서 텍스트 검색")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        sys.exit(f"[error] 파일 없음: {path}")

    print(f"\n[file] {path}  ({path.stat().st_size:,} bytes)\n")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"[error] JSON 파싱 실패: {e}")

    # 키 경로 따라 들어가기
    target = get_path(data, args.key) if args.key else data
    if isinstance(target, str) and target.startswith("<"):
        sys.exit(target)

    # ─ 검색 모드
    if args.search:
        hits = search_in(target, args.search)
        print(f"[search] '{args.search}' — {len(hits)}건 발견")
        for p, v in hits[:20]:
            print(f"  {p}: {describe(v, 80)}")
        if len(hits) > 20:
            print(f"  ... 외 {len(hits) - 20}건")
        return

    # ─ 트리 모드
    if args.tree:
        print(f"[tree] {args.key or '<root>'}: {describe(target, 40)}")
        print_tree(target)
        return

    # ─ 일반 모드: 최상위 요약 + 샘플
    print(f"[type] {describe(target, 80)}")

    if isinstance(target, dict):
        print(f"\n[keys] {list(target.keys())}\n")
        for k, v in list(target.items())[:args.sample]:
            print(f"  · {k}: {describe(v, 100)}")
            if isinstance(v, list) and v:
                print(f"      └─ first item: {describe(v[0], 80)}")
        if len(target) > args.sample:
            print(f"  ... ({len(target) - args.sample}개 키 더 있음)")
    elif isinstance(target, list):
        print(f"\n[list len] {len(target)}")
        for i, item in enumerate(target[:args.sample]):
            print(f"  [{i}] {describe(item, 100)}")
            if isinstance(item, dict):
                for k, v in list(item.items())[:5]:
                    print(f"        {k}: {describe(v, 60)}")
        if len(target) > args.sample:
            print(f"  ... ({len(target) - args.sample}개 더 있음)")
    else:
        print(f"\n[value] {target!r}")


if __name__ == "__main__":
    main()
