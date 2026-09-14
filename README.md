# vv · Sileo 软件源

> **源地址：`https://fatekingcsr.github.io/vv/`** ← Sileo 里填这个
> 仓库：https://github.com/fatekingcsr/vv ｜ 状态：**已上线（2026-09-14 验证通过）**

一个**纯静态**的 Sileo / Cydia 软件源，托管在 GitHub Pages 上，不需要服务器和数据库。
索引由 `tools/gen_repo.py` 用纯 Python 生成（解 `.deb` 不需要 `dpkg-deb` / `ar` / `xz`）。

在 Sileo 里添加：**软件源 → 右上角 + → 粘贴 `https://fatekingcsr.github.io/vv/` → 添加**

---

## 目录结构

```
vv/                                ← 这个目录 = GitHub 仓库根目录
├── index.html                     ← 源落地页（打开源地址看到的就是它）
├── CydiaIcon.png                  ← 源图标，Sileo 里显示（换自己的 90x90 PNG 即可）
├── repo.json                      ← 源配置：名称 / 简介 / 维护者 / 源地址
├── Packages                       ← 源索引（Sileo 读这个）
├── Packages.gz / Packages.bz2     ← 索引的压缩版（Sileo 优先读 .bz2）
├── Release                        ← 源元信息 + MD5 / SHA256（★ 缺了 Sileo 就不认源）
├── repo-data.js / packages.json   ← 给落地页 / 其他工具用的 JSON 数据
├── debs/                          ← 你的 .deb 包都放这里
│   └── com.wang.demo.tweak_1.0.0_iphoneos-arm64.deb   （示例包，随时可删）
├── tools/
│   ├── gen_repo.py                ← 索引生成器
│   ├── publish.py                 ← ★ 一键发布插件（复制 deb + 重建索引 + 推送）
│   └── build-repo.yml             ← 自动重建工作流（见下方「方式 C」）
├── .gitattributes                 ← 强制 LF，防止 CRLF 弄坏校验和
├── .gitignore                     ← 注意：**不要**忽略 Packages / Release
└── .nojekyll                      ← 必须，关掉 Jekyll
```

---

## 以后加新插件

### 方式 A：一条命令（推荐 ⭐）

```bash
python tools/publish.py 你的新插件.deb
```

就这一条。它会自动完成：

1. 把 `.deb` 复制进 `debs/`
2. 重建全部索引（`Packages` / `.gz` / `.bz2` / `Release` / `repo-data.js` / `packages.json`）
3. `git add` + `commit` + `push`
4. **如果 `github.com:443` 又抽风推不上去，自动改用 `api.github.com` 的 Contents API 上传**（国内很稳）

其他用法：

```bash
python tools/publish.py                          # 没有新包，只重建索引并发布
python tools/publish.py a.deb b.deb              # 一次加多个
python tools/publish.py --remove 老插件.deb      # 移除某个包（从 debs/ 删掉）再发布
python tools/publish.py --dry-run 新插件.deb     # 只改本地不推送，先看看效果
python tools/publish.py --api 新插件.deb         # 强制走 API 上传，跳过 git push
```

发布完成后等 1～2 分钟 Pages 部署完，手机上打开 Sileo 下拉刷新即可看到新版。

### 方式 B：手动 git

```bash
cp 新插件.deb debs/
python tools/gen_repo.py
git add -A && git commit -m "add: 新插件 v1.1.0" && git push
```

### 方式 C：全自动（需要先启用一次）

仓库里已经准备好了工作流，但**因为当前 GitHub 登录凭据缺少 `workflow` 权限，没能自动放到位**。
启用方法（二选一）：

- **网页操作**：打开 https://github.com/fatekingcsr/vv/new/main
  文件名填 `.github/workflows/build-repo.yml`，把 `tools/build-repo.yml` 的内容整段粘进去，提交。
- **命令行**：在电脑上跑 `gh auth refresh -h github.com -s workflow` 授权后告诉我，我帮你放好。

启用后，以后只要 push 到 `debs/`，GitHub 就会自动重建索引并提交回来（适合你在别的机器上直接传文件）。

> 首次运行若报 `permission denied`：**Settings → Actions → General → Workflow permissions**
> 选 **Read and write permissions**，再重跑一次工作流。

### 发布前的自检清单

```bash
# 1. deb 的架构要和你的设备对得上（rootless 是 iphoneos-arm64）
python tools/gen_repo.py | grep -i architecture

# 2. 索引里的包名/版本对了吗
grep -E "^(Package|Version|Architecture):" Packages

# 3. 发布完确认线上生效
curl -s https://fatekingcsr.github.io/vv/Packages | grep -E "^(Package|Version):"
```

> ⚠️ Theos 打包 rootless 插件时记得 `THEOS_PACKAGE_SCHEME = rootless`，
> 否则 `Architecture` 会是 `iphoneos-arm`，Dopamine 设备上 Sileo 不显示这个包。

---

## 两个待办（手机上 1 分钟能搞定）

1. **删掉没用的 Jekyll 工作流**：https://github.com/fatekingcsr/vv/delete/main/.github/workflows/jekyll-docker.yml
   （它是 GitHub 建仓库时自动塞的模板，对源毫无用处，还会每次 push 都触发失败）
2. **删掉示例包**（等你的真插件上传后）：删掉 `debs/com.wang.demo.tweak_*.deb`，
   再跑一次 `python tools/gen_repo.py` 并 push。

---

## 排错

**Sileo 提示 "The source could not be found"**
- 浏览器打开 `https://fatekingcsr.github.io/vv/Packages` 能否看到纯文本？打不开说明 Pages 没部署好。
- 源地址**结尾必须有 `/`**；必须 HTTPS（Pages 默认就是）。

**源能加但里面没插件**
- 检查 `Release` 里的 `Architectures` 是否含你设备架构：rootless（Dopamine / palera1n）是
  `iphoneos-arm64`，Theos 打包时记得 `THEOS_PACKAGE_SCHEME = rootless`。
- 检查 `Packages` 里 `Filename: ./debs/xxx.deb` 对应的文件在仓库里真的存在。

**安装报 hash mismatch / 下载 404**
- `.deb` 改过但索引没重建 → 重跑 `python tools/gen_repo.py` 并 push。

**踩过的坑（别再犯）**
- ❌ `.gitignore` 里写了 `Packages` / `Release` → 索引根本没提交，源必然打不开。
- ❌ 缺 `Release` 文件 → Sileo 直接不认这个源。
- ❌ Windows 上 `Path.write_text` 会把 `\n` 写成 `\r\n`，导致 `Release` 里的校验和与实际文件不符
  → 已用 `.gitattributes` + 脚本内 bytes 写入修掉。
- ❌ `gzip.compress(data, 9)` 在 Python 3.11+ 会把**当前时间**写进 gzip 头，导致同样的索引每次
  生成的 `Packages.gz` 字节都不同 → 自动构建永远判定"有变化"，无限提交。
  → 已改成 `gzip.compress(raw, 9, mtime=0)`。
- ❌ Pages 的 `build_type` 被设成 `workflow`（靠 Actions 发布）但工作流是废的 → 站点永远 404。
  正确做法是 **Deploy from a branch → main → /(root)**。
- ❌ `github.com:443` 在国内会间歇性断连（`Recv failure: Connection was reset`），
  但 `api.github.com` 一直通 → `tools/publish.py` 已内置 API 兜底上传。

---

## 换源名 / 换地址

改 `repo.json` 后重新生成：

| 字段 | 说明 |
| --- | --- |
| `origin` / `label` / `name` | 源名称，Sileo 里显示（当前 `vv`） |
| `description` / `maintainer` | 源简介 / 维护者 |
| `url` | 源地址，必须以 `/` 结尾 |
| `accent` | 落地页主色调 |
| `architectures` | `iphoneos-arm64`（rootless）/ `iphoneos-arm`（老越狱） |

```bash
python tools/gen_repo.py --url https://fatekingcsr.github.io/vv/
```

## 用自定义域名

仓库根目录加 `CNAME` 文件（内容为域名），域名服务商加 CNAME 记录指向 `fatekingcsr.github.io`，
再到 **Settings → Pages → Custom domain** 填域名并开启 HTTPS，
最后把 `repo.json` 的 `url` 改掉并重新生成索引。
