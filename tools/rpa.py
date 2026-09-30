#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPA-3.0 / RPA-2.0 解包器（只读，纯标准库）。

RPA-3.0 布局（自 renpy/loader.py 的归档写出逻辑反推，已在本游戏上实测）：
    第 1 行 : "RPA-3.0 <hex offset of index> <hex key>\n"
    其后     : 到 offset 为止是文件数据区
    index    : zlib 压缩的 pickle 对象
               { "路径/文件名": [ (offset, length, prefix), ... ] }
               offset / length 都要与 key 异或才是真值
    prefix   : 该分片的原始前缀字节，需原样写回

本脚本**不修改游戏目录**，只往 -o 指定的目录写。
"""

from __future__ import annotations

import argparse
import io
import os
import pickle
import struct
import sys
import zlib


def read_header(fh: io.BufferedReader) -> tuple[str, int, int | None]:
    """返回 (版本, index 偏移, key)。key 为 None 表示 RPA-2.0。"""
    line = fh.readline().decode("utf-8", "replace").strip()
    parts = line.split()

    if parts[0] == "RPA-3.0":
        return "RPA-3.0", int(parts[1], 16), int(parts[2], 16)
    if parts[0] == "RPA-2.0":
        return "RPA-2.0", int(parts[1], 16), None
    if parts[0] == "RPA-1.0":
        raise SystemExit("RPA-1.0 未支持（本作不是）")
    raise SystemExit(f"不是 RPA 归档，首行: {line!r}")


def load_index(fh: io.BufferedReader, version: str, offset: int, key: int | None) -> dict:
    fh.seek(offset)
    raw = zlib.decompress(fh.read())
    index = pickle.loads(raw)

    if version != "RPA-3.0" or key is None:
        return index

    out = {}
    for name, entries in index.items():
        fixed = []
        for item in entries:
            if len(item) >= 2:
                o, ln = item[0] ^ key, item[1] ^ key
                rest = tuple(item[2:])
                fixed.append((o, ln, *rest))
            else:
                fixed.append(tuple(item))
        out[name] = fixed
    return out


def extract(rpa_path: str, out_dir: str, only: list[str] | None, list_only: bool) -> int:
    with open(rpa_path, "rb") as fh:
        version, offset, key = read_header(fh)
        index = load_index(fh, version, offset, key)

        names = sorted(index)
        if only:
            pats = [p.lower() for p in only]
            names = [n for n in names if any(p in n.lower() for p in pats)]

        if list_only:
            for n in names:
                size = sum(e[1] for e in index[n])
                print(f"{size:>12}  {n}")
            print(f"--- {len(names)} / {len(index)} 个条目", file=sys.stderr)
            return 0

        count = 0
        for n in names:
            target = os.path.join(out_dir, n.replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                for entry in index[n]:
                    o, ln = entry[0], entry[1]
                    prefix = entry[2] if len(entry) > 2 else b""
                    fh.seek(o)
                    data = fh.read(ln)
                    if len(data) != ln:
                        raise SystemExit(f"{n}: 读到的字节数不符（{len(data)} != {ln}）")
                    if prefix:
                        out.write(prefix)
                    out.write(data)
            count += 1
        print(f"解出 {count} 个文件 -> {out_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="RPA-3.0 解包器")
    ap.add_argument("rpa")
    ap.add_argument("-o", "--out", default=".")
    ap.add_argument("--only", action="append", help="只处理路径含该子串的条目，可重复")
    ap.add_argument("-l", "--list", action="store_true", dest="list_only", help="只列清单")
    args = ap.parse_args()
    return extract(args.rpa, args.out, args.only, args.list_only)


if __name__ == "__main__":
    raise SystemExit(main())
