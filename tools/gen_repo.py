#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sileo / Cydia 软件源索引生成器（纯 Python，Windows / Git Bash 可用，无需 dpkg-deb / ar / xz）

扫描 debs/ 目录下所有 .deb，读取其中的 control 文件，生成一个 Sileo
可以直接添加的软件源所需的全部文件：

    Packages        未压缩索引（Sileo 读取的原始文件）
    Packages.gz     gzip 压缩索引
    Packages.bz2    bzip2 压缩索引（Sileo 优先读取）
    Release         源元信息 + 各索引文件的校验和
    repo-data.js    源落地页 index.html 用的内联数据（file:// 也能正常显示）
    packages.json   通用 JSON 索引，方便其他工具复用
    CydiaIcon.png   源图标（缺失时自动生成一个默认的）

用法:
    python tools/gen_repo.py            # 重建索引
    python tools/gen_repo.py --demo     # 顺便造一个演示包，验证整条链路
"""

import argparse
import bz2
import gzip
import hashlib
import io
import json
import lzma
import re
import struct
import sys
import tarfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEBS_DIR = ROOT / "debs"
CONFIG_PATH = ROOT / "repo.json"

DEFAULT_CONFIG = {
    "origin": "My Repo",
    "label": "My Repo",
    "name": "My Repo",
    "description": "自建 Sileo 软件源",
    "maintainer": "Anonymous <anonymous@example.com>",
    "url": "https://example.com/",
    "icon": "CydiaIcon.png",
    "accent": "#5b8cff",
    "component": "main",
    "codename": "ios",
    "suite": "stable",
    "version": "1.0",
    "architectures": ["iphoneos-arm64", "iphoneos-arm"],
    "featured": [],
}

# Packages 索引里字段的输出顺序（不在表里的字段按原顺序追加到末尾）
FIELD_ORDER = [
    "Package", "Name", "Version", "Architecture", "Description", "Section",
    "Essential", "Depends", "Pre-Depends", "Recommends", "Suggests",
    "Conflicts", "Breaks", "Replaces", "Provides",
    "Maintainer", "Author", "Sponsor", "Icon", "Depiction", "Sileodepiction",
    "ModernDepiction", "Homepage", "Tag",
    "Filename", "Size", "MD5sum", "SHA1", "SHA256", "SHA512", "Installed-Size",
]

# 我们自己重新计算的字段，control 里若存在则丢弃，避免重复
RECOMPUTED = {"Filename", "Size", "MD5sum", "SHA1", "SHA256", "SHA512"}

# 占位地址检测
_PLACEHOLDER = re.compile(r"example\.(com|org)|your-username|your-domain", re.I)


def _url_ok(url: str) -> bool:
    return not _PLACEHOLDER.search(url or "")


def write_text_lf(path, text: str) -> None:
    """始终以 LF 写文件。

    Windows 上 Path.write_text 默认会把 \\n 翻译成 \\r\\n，而 GitHub Actions 跑在
    Linux 上写的是 LF —— 两边不一致会导致索引每次都被判为「有变化」来回抖动，
    也可能让 APT/Sileo 的校验和出现意外差异。所以统一走 bytes 写入。
    """
    Path(path).write_bytes(text.encode("utf-8"))


# --------------------------------------------------------------------------- #
# 一、读取 deb（ar 归档 → control.tar.* → ./control）
# --------------------------------------------------------------------------- #

def iter_ar(data: bytes):
    """遍历 ar 归档成员，yield (name, body)。"""
    if data[:8] != b"!<arch>\n":
        raise ValueError("不是合法的 ar 归档（deb 文件头应为 !<arch>）")
    off = 8
    while off + 60 <= len(data):
        hdr = data[off:off + 60]
        name = hdr[0:16].decode("utf-8", "replace").strip()
        try:
            size = int(hdr[48:58].decode("ascii", "replace").strip() or "0")
        except ValueError:
            break
        body = data[off + 60: off + 60 + size]
        yield name.rstrip("/"), body
        off += 60 + size + (size % 2)


def decompress(blob: bytes, name: str) -> bytes:
    """按扩展名解压 tar 成员。"""
    if name.endswith(".gz"):
        return gzip.decompress(blob)
    if name.endswith(".xz"):
        return lzma.decompress(blob)
    if name.endswith(".lzma"):
        try:
            return lzma.decompress(blob, format=lzma.FORMAT_ALONE)
        except Exception:
            return lzma.decompress(blob)
    if name.endswith(".zst"):
        try:
            import zstandard  # type: ignore
        except ImportError:
            raise SystemExit(
                "[!] 这个 deb 用了 zstd 压缩，需要先装依赖：\n"
                "    pip install zstandard"
            )
        return zstandard.ZstdDecompressor().decompress(blob, max_output_size=1 << 30)
    return blob  # 未压缩 tar


def parse_control(text: str) -> dict:
    """解析 Debian control 的 RFC822 格式（含续行）。"""
    fields, key = {}, None
    for line in text.splitlines():
        if not line.strip():
            key = None
            continue
        if line[0] in " \t" and key:
            fields[key] = fields[key] + "\n" + line.strip()
        elif ":" in line:
            k, v = line.split(":", 1)
            key, fields[key.strip()] = k.strip(), v.strip()
    return fields


def read_deb(path: Path) -> dict:
    """从一个 .deb 中取出 control 字段，并补充计算 Installed-Size。"""
    data = path.read_bytes()
    control_text, data_tar_size = None, None

    for name, body in iter_ar(data):
        if name.startswith("control.tar"):
            blob = decompress(body, name)
            with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                for member in tf.getmembers():
                    if member.name.lstrip("./") == "control":
                        raw = tf.extractfile(member).read()
                        try:
                            control_text = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            control_text = raw.decode("latin-1")
                        break
        elif name.startswith("data.tar"):
            blob = decompress(body, name)
            with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                data_tar_size = sum(m.size for m in tf.getmembers() if m.isfile())

    if control_text is None:
        raise ValueError("deb 里没有找到 control 文件")

    fields = parse_control(control_text)
    if data_tar_size is not None and "Installed-Size" not in fields:
        # dpkg 的 Installed-Size 单位是 KiB
        fields["Installed-Size"] = str(max(1, round(data_tar_size / 1024)))
    return fields


# --------------------------------------------------------------------------- #
# 二、生成索引条目
# --------------------------------------------------------------------------- #

def emit_entry(fields: dict) -> str:
    """把字段字典还原成 Packages 里的一段 control 文本。"""
    keys = [k for k in FIELD_ORDER if k in fields]
    keys += [k for k in fields if k not in FIELD_ORDER]
    lines = []
    for k in keys:
        parts = str(fields[k]).split("\n")
        lines.append(f"{k}: {parts[0]}")
        for extra in parts[1:]:
            lines.append(f" {extra.strip()}")
    return "\n".join(lines)


def sha256_of(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def md5_of(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()


def build_index(config: dict):
    entries, meta = [], []
    debs = sorted(p for p in DEBS_DIR.glob("*.deb"))

    for deb in debs:
        try:
            fields = read_deb(deb)
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] 跳过 {deb.name}：{exc}")
            continue

        blob = deb.read_bytes()
        for k in list(RECOMPUTED):
            fields.pop(k, None)

        rel_path = f"./{deb.relative_to(ROOT).as_posix()}"
        fields["Filename"] = rel_path
        fields["Size"] = str(len(blob))
        fields["MD5sum"] = md5_of(blob)
        fields["SHA256"] = sha256_of(blob)
        fields.setdefault("Section", "Tweaks")
        if config["maintainer"]:
            fields.setdefault("Maintainer", config["maintainer"])

        entries.append(emit_entry(fields))
        meta.append({
            "id": fields.get("Package", deb.stem),
            "name": fields.get("Name") or fields.get("Package", deb.stem),
            "version": fields.get("Version", "?"),
            "architecture": fields.get("Architecture", "iphoneos-arm64"),
            "section": fields.get("Section", "Tweaks"),
            "description": fields.get("Description", ""),
            "author": fields.get("Author") or fields.get("Maintainer", ""),
            "installedSize": fields.get("Installed-Size", ""),
            "size": len(blob),
            "filename": rel_path,
            "icon": fields.get("Icon", ""),
            "depiction": fields.get("Sileodepiction") or fields.get("Depiction", ""),
            "homepage": fields.get("Homepage", ""),
            "depends": fields.get("Depends", ""),
        })
        print(f"  [+] {fields.get('Package')} {fields.get('Version')}  ({deb.name})")

    return entries, meta


# --------------------------------------------------------------------------- #
# 三、写出各文件
# --------------------------------------------------------------------------- #

def write_packages(entries) -> dict:
    text = "\n\n".join(entries) + ("\n" if entries else "")
    raw = text.encode("utf-8")
    # mtime=0：否则 gzip 头里会写入「当前时间」，导致每次生成的 Packages.gz 字节都不同，
    # 索引永远被判为「有变化」，Actions 会无限提交。bz2 本身是确定性的。
    gz = gzip.compress(raw, 9, mtime=0)
    bz = bz2.compress(raw, 9)

    (ROOT / "Packages").write_bytes(raw)
    (ROOT / "Packages.gz").write_bytes(gz)
    (ROOT / "Packages.bz2").write_bytes(bz)
    return {"Packages": (raw, len(raw)),
            "Packages.gz": (gz, len(gz)),
            "Packages.bz2": (bz, len(bz))}


def write_release(config: dict, indices: dict, arches) -> None:
    stamp = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    lines = [
        f"Origin: {config['origin']}",
        f"Label: {config['label']}",
        f"Suite: {config['suite']}",
        f"Version: {config['version']}",
        f"Codename: {config['codename']}",
        f"Architectures: {' '.join(arches)}",
        f"Components: {config['component']}",
        f"Description: {config['description']}",
        f"Date: {stamp}",
        "MD5Sum:",
    ]
    for name, (blob, size) in indices.items():
        lines.append(f" {md5_of(blob)} {size} {name}")
    lines.append("SHA256:")
    for name, (blob, size) in indices.items():
        lines.append(f" {sha256_of(blob)} {size} {name}")
    lines.append("")
    write_text_lf(ROOT / "Release", "\n".join(lines))


def write_json(config: dict, meta) -> None:
    payload = dict(config)
    payload["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["packageCount"] = len(meta)
    payload["packages"] = meta

    write_text_lf(ROOT / "packages.json",
                  json.dumps(payload, ensure_ascii=False, indent=2))
    write_text_lf(ROOT / "repo-data.js",
                  "window.SILEO_REPO = " + json.dumps(payload, ensure_ascii=False) + ";\n")


def write_featured(config: dict) -> None:
    """sileo-featured.json —— Sileo 「精选」页的横幅，没配就不生成。"""
    banners = config.get("featured") or []
    path = ROOT / "sileo-featured.json"
    if not banners:
        if path.exists():
            path.unlink()
        return
    data = {
        "class": "FeaturedBannersView",
        "itemSize": "{263, 148}",
        "itemCornerRadius": 8,
        "banners": banners,
    }
    write_text_lf(path, json.dumps(data, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# 四、默认图标（纯 Python 画一个 PNG，不依赖 Pillow）
# --------------------------------------------------------------------------- #

def write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = b"".join(b"\x00" + bytes(pixels[y * width * 4:(y + 1) * width * 4])
                   for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))


def make_default_icon(path: Path, accent: str = "#5b8cff", size: int = 180) -> None:
    """圆角方块 + 渐变 + 白色下载箭头，用来当源图标。"""
    ss = 3                                   # 3x 超采样做抗锯齿
    w = size * ss

    def hex_rgb(h: str):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    top, bot = hex_rgb(accent), tuple(int(c * 0.55) for c in hex_rgb(accent))
    radius = w * 0.235
    cx = w / 2

    # 箭头几何（相对画布比例）
    shaft_hw = w * 0.038
    shaft_top, shaft_bot = w * 0.265, w * 0.545
    head_hw, head_bot = w * 0.155, w * 0.665
    tray_hw, tray_h, tray_top = w * 0.245, w * 0.055, w * 0.735

    hi = bytearray(w * w * 4)
    for y in range(w):
        t = y / (w - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(w):
            # 圆角矩形遮罩
            dx = max(radius - x, x - (w - 1 - radius), 0)
            dy = max(radius - y, y - (w - 1 - radius), 0)
            if dx * dx + dy * dy > radius * radius:
                continue
            idx = (y * w + x) * 4
            hi[idx:idx + 4] = bytes((r, g, b, 255))

    def fill(x0, x1, y0, y1, colour):
        for yy in range(max(0, int(y0)), min(w, int(y1))):
            for xx in range(max(0, int(x0)), min(w, int(x1))):
                i = (yy * w + xx) * 4
                if hi[i + 3]:
                    hi[i:i + 4] = bytes((*colour, 255))

    white = (255, 255, 255)
    fill(cx - shaft_hw, cx + shaft_hw, shaft_top, shaft_bot + 2, white)      # 箭杆
    for yy in range(int(shaft_bot) - 2, int(head_bot)):                      # 箭头
        k = (yy - (shaft_bot - 2)) / max(1.0, head_bot - (shaft_bot - 2))
        half = head_hw * (1 - k)
        fill(cx - half, cx + half, yy, yy + 1, white)
    for yy in range(int(tray_top), int(tray_top + tray_h)):                  # 托盘
        fill(cx - tray_hw, cx + tray_hw, yy, yy + 1, white)

    # 降采样
    out = bytearray(size * size * 4)
    n = ss * ss
    for y in range(size):
        for x in range(size):
            ar = ag = ab = aa = 0
            for sy in range(ss):
                base = ((y * ss + sy) * w + x * ss) * 4
                for sx in range(ss):
                    i = base + sx * 4
                    a = hi[i + 3]
                    ar += hi[i] * a
                    ag += hi[i + 1] * a
                    ab += hi[i + 2] * a
                    aa += a
            o = (y * size + x) * 4
            if aa:
                out[o:o + 3] = bytes((ar // aa, ag // aa, ab // aa))
            out[o + 3] = aa // n

    write_png(path, size, size, out)


# --------------------------------------------------------------------------- #
# 五、演示包（--demo）
# --------------------------------------------------------------------------- #

def build_demo_deb(config: dict) -> Path:
    """拼一个结构完全合法的 .deb，用来验证整条链路。"""
    control = (
        "Package: com.wang.demo.tweak\n"
        "Name: Demo Tweak\n"
        "Version: 1.0.0\n"
        "Architecture: iphoneos-arm64\n"
        "Section: Tweaks\n"
        f"Maintainer: {config['maintainer']}\n"
        "Author: Wang\n"
        "Depends: mobilesubstrate, firmware (>= 14.0)\n"
        "Description: 演示插件（gen_repo.py --demo 生成）\n"
        " 仅用于验证 Sileo 源链路，验证完可以删掉 debs/ 里的这个包。\n"
    )
    layout = (
        "Package: com.wang.demo.pkg\n"
        "Name: Demo Package\n"
        "Version: 1.0.0\n"
        "Architecture: iphoneos-arm64\n"
        "Section: Tweaks\n"
        "Description: 演示用（空包）\n"
    )

    def tar_bytes(name: str, payload: bytes) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(payload), 0o644, 0
            tf.addfile(info, io.BytesIO(payload))
        return buf.getvalue()

    def ar_bytes(members) -> bytes:
        out = bytearray(b"!<arch>\n")
        for name, body in members:
            out += (f"{name:<16}{0:<12}{0:<6}{0:<6}{'100644':<8}"
                    f"{len(body):<10}`\n").encode("ascii")
            out += body + (b"\n" if len(body) % 2 else b"")
        return bytes(out)

    deb = DEBS_DIR / "com.wang.demo.tweak_1.0.0_iphoneos-arm64.deb"
    DEBS_DIR.mkdir(parents=True, exist_ok=True)
    deb.write_bytes(ar_bytes([
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", gzip.compress(tar_bytes("./control", control.encode()))),
        ("data.tar.gz", gzip.compress(tar_bytes("./var/jb/Library/MobileSubstrate/"
                                                "DynamicLibraries/DemoTweak.dylib", layout.encode()))),
    ]))
    return deb


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="Sileo 软件源索引生成器")
    ap.add_argument("--demo", action="store_true", help="生成一个演示 deb 用于验证")
    ap.add_argument("--url", metavar="URL",
                    help="顺手把 repo.json 里的源地址改成这个（GitHub Pages 地址，必须以 / 结尾）")
    args = ap.parse_args()

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            print(f"[!] repo.json 解析失败，改用默认配置：{exc}")
    else:
        write_text_lf(CONFIG_PATH, json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    if args.url:
        url = args.url.strip()
        if not url.endswith("/"):
            url += "/"
        config["url"] = url
        write_text_lf(CONFIG_PATH, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        print(f"> 已更新源地址: {url}")

    if not config["url"].endswith("/"):
        config["url"] += "/"

    if not _url_ok(config["url"]):
        print(f"[!] 提示：源地址还是占位地址（{config['url']}），Sileo 打不开。\n"
              f"    GitHub Pages 地址形如：\n"
              f"      用户主页仓库  https://<用户名>.github.io/\n"
              f"      普通项目仓库  https://<用户名>.github.io/<仓库名>/\n"
              f"    一键修改：python tools/gen_repo.py --url https://<用户名>.github.io/")

    DEBS_DIR.mkdir(parents=True, exist_ok=True)
    if not any(DEBS_DIR.iterdir()):
        write_text_lf(DEBS_DIR / ".gitkeep", "")

    print(f"> 源目录: {ROOT}")
    print(f"> 名称:   {config['origin']}")

    if args.demo:
        demo = build_demo_deb(config)
        print(f"> 演示包: {demo.name}")

    if not (ROOT / config["icon"]).exists():
        make_default_icon(ROOT / config["icon"], config["accent"])
        print(f"> 已生成默认源图标 {config['icon']}（可以换成自己的 90x90 PNG）")

    print("\n> 扫描 debs/ ...")
    entries, meta = build_index(config)
    if not entries:
        print("  (debs/ 里没有 .deb，先生成空索引)")

    indices = write_packages(entries)

    arches = []
    for a in config["architectures"] + [m["architecture"] for m in meta]:
        if a and a not in arches:
            arches.append(a)
    write_release(config, indices, arches)
    write_json(config, meta)
    write_featured(config)

    print(f"\n完成：{len(meta)} 个包")
    print(f"  Packages      {len(indices['Packages'][0]):>8} B")
    print(f"  Packages.gz   {len(indices['Packages.gz'][0]):>8} B")
    print(f"  Packages.bz2  {len(indices['Packages.bz2'][0]):>8} B")
    print(f"  Release / repo-data.js / packages.json 已更新")
    print(f"\n下一步：把整个 {ROOT.name}/ 目录传到你的服务器 / GitHub Pages，"
          f"源地址填 {config['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
