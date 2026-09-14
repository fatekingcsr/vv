#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键发布插件到 Sileo 源（vv）

做的事情：
  1. 把指定的 .deb 复制进 debs/
  2. 重建索引（Packages / Packages.gz / Packages.bz2 / Release / repo-data.js / packages.json）
  3. git add + commit + push
  4. push 失败（github.com:443 在国内经常断）时，自动改走 api.github.com 的 Contents API 上传

用法:
    python tools/publish.py                          # 只重建索引并发布（比如你手动删了某个 deb）
    python tools/publish.py 新插件.deb               # 加入一个新包并发布
    python tools/publish.py a.deb b.deb              # 一次加多个
    python tools/publish.py --remove 老插件.deb      # 从 debs/ 移除某个包再发布
    python tools/publish.py --dry-run 新插件.deb     # 只改本地不推送，先看看效果
    python tools/publish.py --api 新插件.deb         # 强制走 API 上传（跳过 git push）
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEBS_DIR = ROOT / "debs"
GEN = Path(__file__).resolve().parent / "gen_repo.py"

# 这些路径的改动需要 GitHub 的 workflow 权限，本工具的 API 模式推不了，直接跳过
WORKFLOW_PREFIX = ".github/workflows/"

GH_CANDIDATES = [
    r"C:\Program Files\GitHub CLI\gh.exe",
    r"C:\Program Files (x86)\GitHub CLI\gh.exe",
    "/usr/bin/gh",
    "/usr/local/bin/gh",
    "/opt/homebrew/bin/gh",
]


# --------------------------------------------------------------------------- #

def run(cmd, **kw):
    """执行命令，返回 (returncode, stdout+stderr)。超时/异常都当成失败返回，不抛出。"""
    if sys.platform == "win32":
        kw.setdefault("encoding", "utf-8")
        kw.setdefault("errors", "replace")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, **kw)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 1, f"(命令超过 {kw.get('timeout')} 秒未返回)"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def has_git() -> bool:
    return shutil.which("git") is not None


def find_gh():
    for p in GH_CANDIDATES:
        if Path(p).exists():
            return p
    return shutil.which("gh")


def git(*args, check=False):
    code, out = run(["git", "-C", str(ROOT), *args])
    if check and code != 0:
        raise SystemExit(out.strip())
    return code, out.strip()


def repo_slug():
    """从 origin 里取出 owner/repo。"""
    _, url = git("remote", "get-url", "origin")
    url = url.strip().removesuffix(".git")
    if "github.com" not in url:
        return None
    tail = url.split("github.com", 1)[1].lstrip(":/")
    parts = [p for p in tail.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None


# --------------------------------------------------------------------------- #
# 1. 准备文件
# --------------------------------------------------------------------------- #

def stage_debs(paths, remove):
    DEBS_DIR.mkdir(parents=True, exist_ok=True)
    changed = []

    for raw in remove:
        p = Path(raw)
        target = p if p.is_absolute() else DEBS_DIR / p.name
        if target.exists():
            target.unlink()
            changed.append(f"移除 {target.name}")
        else:
            print(f"  [!] 找不到 {target}，跳过")

    for raw in paths:
        src = Path(raw).expanduser()
        if not src.exists():
            raise SystemExit(f"[x] 找不到文件：{src}")
        if src.suffix.lower() != ".deb":
            raise SystemExit(f"[x] 不是 .deb 文件：{src}")
        dst = DEBS_DIR / src.name
        if src.resolve() == dst.resolve():
            changed.append(f"已在 debs/ 中：{dst.name}")
        else:
            shutil.copy2(src, dst)
            changed.append(f"加入 {dst.name}（{dst.stat().st_size / 1024:.1f} KB）")

    (DEBS_DIR / ".gitkeep").touch()
    return changed


def rebuild_index():
    code, out = run([sys.executable, str(GEN)], cwd=str(ROOT))
    print(out.rstrip())
    if code != 0:
        raise SystemExit("[x] 索引重建失败，已中止（没有推送任何东西）")


# --------------------------------------------------------------------------- #
# 2. 提交
# --------------------------------------------------------------------------- #

def commit_changes(message):
    git("add", "-A")
    code, out = git("diff", "--cached", "--name-status")
    if not out:
        return []
    files = [line.split("\t", 1)[1] if "\t" in line else line for line in out.splitlines()]
    code, out = git("commit", "-m", message)
    if code != 0 and "nothing to commit" not in out:
        raise SystemExit(f"[x] git commit 失败：\n{out}")
    return files


def sync_with_remote():
    """推送前先 fetch，如果远端有本地没有的提交（比如上次走 API 上传产生的），先 rebase 对齐。"""
    code, _ = run(["git", "-C", str(ROOT), "fetch", "-q", "origin"], timeout=45)
    if code != 0:
        print("  · fetch 失败（github.com 不通），跳过对齐")
        return False
    code, behind = git("rev-list", "--count", "main..origin/main")
    try:
        n = int(behind or 0)
    except ValueError:
        n = 0
    if n <= 0:
        return True
    code, out = run(["git", "-C", str(ROOT), "rebase", "origin/main"])
    if code == 0:
        print(f"  · 已 rebase 到 origin/main（远端有 {n} 个本地没有的提交）")
        return True
    run(["git", "-C", str(ROOT), "rebase", "--abort"])
    print(f"  · rebase 失败，已回滚：{out.strip().splitlines()[:1]}")
    return False


def port_open(host="github.com", port=443, timeout=3.0):
    """快速探测 github.com:443 是否可达，避免明知不通还傻等 4 次 push 重试。"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def try_git_push(attempts=3, wait=3):
    """github.com:443 在国内会间歇性不通，多试几次。"""
    if not port_open():
        print("  · github.com:443 无法连接，跳过 git push，直接走 API")
        return False, "github.com:443 不可达"
    sync_with_remote()
    for i in range(1, attempts + 1):
        code, out = run(["git", "-C", str(ROOT), "push", "origin", "main"],
                        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=90)
        if code == 0:
            return True, f"git push 成功（第 {i} 次尝试）"
        last = out.strip().splitlines()[-1] if out.strip() else "(无输出)"
        print(f"  · 第 {i} 次 git push 失败：{last}")
        if i < attempts:
            time.sleep(wait)
    return False, last


# --------------------------------------------------------------------------- #
# 3. API 兜底上传（走 api.github.com，国内稳定）
# --------------------------------------------------------------------------- #

def _gh_api(gh, args, payload=None):
    code, out = run([gh, "api", *args, "--input", "-"],
                    input=json.dumps(payload) if payload is not None else "")
    if code != 0:
        raise RuntimeError(out.strip())
    return json.loads(out) if out.strip() else {}


def push_via_api(gh, slug, files, message):
    owner, repo = slug.split("/", 1)
    ok, skipped, failed = [], [], []

    for path in files:
        if path.startswith(WORKFLOW_PREFIX):
            skipped.append(path)
            continue
        local = ROOT / path
        try:
            # 先看远端有没有同名文件，有就要带上它的 sha
            code, out = run([gh, "api", f"repos/{owner}/{repo}/contents/{path}?ref=main"])
            sha = json.loads(out).get("sha") if code == 0 and out.strip() else None

            if not local.exists():
                if not sha:
                    continue
                _gh_api(gh, ["-X", "DELETE",
                             f"repos/{owner}/{repo}/contents/{path}"],
                        {"message": message, "sha": sha, "branch": "main"})
            else:
                payload = {"message": message, "branch": "main",
                           "content": base64.b64encode(local.read_bytes()).decode("ascii")}
                if sha:
                    payload["sha"] = sha
                _gh_api(gh, ["-X", "PUT", f"repos/{owner}/{repo}/contents/{path}"], payload)
            ok.append(path)
            print(f"  · API 上传成功 {path}")
        except Exception as exc:  # noqa: BLE001
            failed.append((path, str(exc)))
            print(f"  · API 上传失败 {path}：{exc}")

    return ok, skipped, failed


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="一键发布插件到 Sileo 源")
    ap.add_argument("debs", nargs="*", help="要加入 debs/ 的 .deb 路径")
    ap.add_argument("--remove", nargs="*", default=[], help="要从 debs/ 移除的包名")
    ap.add_argument("--dry-run", action="store_true", help="只改本地，不推送")
    ap.add_argument("--api", action="store_true", help="强制走 API 上传，跳过 git push")
    ap.add_argument("-m", "--message", help="自定义提交信息")
    args = ap.parse_args()

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print(f"> 源目录: {ROOT}\n")

    changes = stage_debs(args.debs, args.remove)
    for c in changes:
        print(f"  + {c}")

    rebuild_index()

    msg = args.message or (
        "release: " + "、".join(Path(d).name for d in args.debs)
        if args.debs else "chore: 重建源索引"
    )
    files = commit_changes(msg)

    if not files:
        # 可能上一次跑过 --dry-run（已经提交但没推），这里补推
        code, out = git("diff", "--name-only", "origin/main..main")
        if out:
            files = out.splitlines()
            print("\n> 本地有已提交但未推送的改动，继续发布。")
        else:
            print("\n没有文件变化，无需推送 —— 源已是最新。")
            return 0
    print(f"\n> 本次要发布的文件 {len(files)} 个：")
    for f in files:
        print(f"    {f}")

    if args.dry_run:
        print("\n--dry-run：已提交到本地，未推送。确认无误后去掉 --dry-run 再跑一次。")
        return 0

    slug = repo_slug()
    method = "git"
    if args.api:
        pushed = False
    else:
        print("\n> git push ...")
        pushed, detail = try_git_push()
        print(f"  {detail}")

    if pushed:
        print(f"\n✅ 已发布到 https://github.com/{slug}")
    else:
        print("\n> git push 不通，改走 api.github.com 的 Contents API ...")
        gh = find_gh()
        if not gh:
            print("[x] 没找到 gh 命令，无法走 API。请等网络恢复后重跑，或先手动 git push。")
            return 1
        if not slug:
            print("[x] 无法从 origin 解析 owner/repo。")
            return 1
        ok, skipped, failed = push_via_api(gh, slug, files, msg)
        print(f"\n✅ 通过 API 上传 {len(ok)} 个文件")
        if skipped:
            print(f"⚠️  跳过 {len(skipped)} 个 workflow 文件（需要 workflow 权限）：{skipped}")
        if failed:
            print("❌ 以下文件未上传成功：")
            for f, e in failed:
                print(f"    {f} -> {e}")
            return 1
        method = "api"

    print(f"\n发布完成（方式：{method}）。")
    print("等 1～2 分钟 GitHub Pages 部署完，手机上打开 Sileo 下拉刷新即可看到。")
    print("自检命令： curl -sI https://fatekingcsr.github.io/vv/Packages | head -1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
