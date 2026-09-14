# vv · Sileo 软件源（GitHub Pages）

一个**纯静态**的 Sileo / Cydia 软件源。整个仓库就是网站本身，托管在 GitHub Pages 上。

> **本源的地址是**：`https://fatekingcsr.github.io/vv/`
> （GitHub 用户名 `fatekingcsr`，仓库名 `vv`）

不需要服务器、不需要数据库、不需要 dpkg-deb —— 索引由 `tools/gen_repo.py` 纯 Python 生成。

---

## 目录结构

```
vv/                                ← 这个目录 = GitHub 仓库根目录
├── index.html                     ← 源落地页（别人打开源地址看到的就是这个）
├── CydiaIcon.png                  ← 源图标，Sileo 里显示的小图标（可换成自己的 90x90 PNG）
├── repo.json                      ← 源配置：名称、简介、维护者、源地址
├── Packages                       ← 源索引（Sileo 读这个）
├── Packages.gz / Packages.bz2     ← 索引的压缩版（Sileo 优先读 .bz2）
├── Release                        ← 源元信息 + 校验和
├── repo-data.js / packages.json   ← 给落地页 / 其他工具用的 JSON 数据
├── debs/                          ← 你的 .deb 包都放这里
│   └── com.wang.demo.tweak_1.0.0_iphoneos-arm64.deb   （示例包，可删）
├── tools/gen_repo.py              ← 索引生成器
├── .github/workflows/build-repo.yml  ← 推包后自动重建索引
└── .nojekyll                       ← 必须，否则 GitHub Pages 的 Jekyll 会干扰
```

---

## 上传到 GitHub（三种方式，手机优先看第 1 种）

### 方式 1：让 AI 直接帮你推（最省事，适合手机）

在 GitHub 上生成一个 **Fine-grained personal access token**，权限只勾
`vv` 这个仓库的 **Contents: Read and write**，把它发给我，我直接在电脑端帮你
建仓库、传文件、开 Pages。手机上什么都不用做。

### 方式 2：GitHub 网页上传（手机可用）

1. 手机浏览器打开 GitHub → **New repository**
2. **Repository name 填 `vv`**，可见性选 **Public**，**不要**勾选 README/.gitignore
3. 创建后进入仓库 → `Add file` → `Upload files`
4. 把本目录里**所有文件**都传上去

> ⚠️ 网页上传**无法创建 `.github` / `debs` 这类空目录**，`.nojekyll` 这种点开头的文件在手机上
> 也不好选。所以网页方式建议先只传这几个**必需文件**跑通：
> `Packages`、`Packages.bz2`、`Packages.gz`、`Release`、`CydiaIcon.png`、`index.html`、
> `repo.json`、`repo-data.js`、`packages.json`，以及 `debs/` 里的 `.deb`。
> 漏了 `.nojekyll` 一般也能用。

### 方式 3：电脑上 git push（推荐，以后更新方便）

```bash
git init
git add -A
git commit -m "init: vv Sileo 软件源"
git branch -M main
git remote add origin https://github.com/fatekingcsr/vv.git
git push -u origin main
```

> 本地 git 还没配身份的话，先跑：
> `git config --global user.name "fatekingcsr"` 和
> `git config --global user.email "你的邮箱"`

---

## 开启 GitHub Pages

仓库 → **Settings** → 左侧 **Pages**：

- **Source**: `Deploy from a branch`
- **Branch**: `main`，目录选 `/ (root)`
- 点 **Save**

等 1～2 分钟，站点地址就是 `https://fatekingcsr.github.io/vv/`。

**验证一下**：手机浏览器直接打开

```
https://fatekingcsr.github.io/vv/Packages
```

能看到 `Package: com.wang.demo.tweak` 这样的**纯文本**内容，就说明源已经可用
（这才是 Sileo 真正读取的文件）。同时打开 `https://fatekingcsr.github.io/vv/`
应该能看到落地页。

---

## 在 Sileo 里添加

1. 打开 Sileo → 底部 **软件源** → 右上角 **+**
2. 粘贴 `https://fatekingcsr.github.io/vv/`
3. 点添加 → 稍等片刻，源里就会出现 `vv` 和里面的插件
4. 点进去 → **获取** → **队列** → **确认** 安装

也可以直接点落地页上的 **「添加到 Sileo」** 按钮，或访问
`sileo://source/https://fatekingcsr.github.io/vv/`。

---

## 以后怎么加新插件

**只推 .deb 就行**，索引会由 GitHub Actions 自动重建：

```bash
cp 新插件.deb debs/
git add debs/
git commit -m "add: 新插件 v1.1.0"
git push
```

推送后 `.github/workflows/build-repo.yml` 会跑一遍 `tools/gen_repo.py`，
把更新后的 `Packages` / `Release` 自动提交回仓库。等 Actions 变绿、Pages 重新部署完
（约 1 分钟），手机上打开 Sileo 下拉刷新即可看到新版。

> 第一次运行如果 Actions 报 `permission denied`，去
> **Settings → Actions → General → Workflow permissions** 选
> **Read and write permissions** 再重新跑一次。

如果想在本地先生成索引：

```bash
python tools/gen_repo.py
python -m http.server 8080     # 浏览器打开 http://localhost:8080/ 预览落地页
```

> 仓库里自带的示例包 `com.wang.demo.tweak` 只是用来验证链路是否通。
> 确认没问题后删掉它再重建一次索引：
>
> ```bash
> rm debs/com.wang.demo.tweak_*.deb
> python tools/gen_repo.py
> ```

---

## 常见问题

**Sileo 提示 "The source could not be found" / 加载失败**
- 直接访问 `https://fatekingcsr.github.io/vv/Packages` 能不能打开？打不开说明 Pages 没部署好，
  或者仓库是私有的（GitHub Pages 免费版只支持 **Public** 仓库）。
- 源地址结尾必须有 `/`。
- 必须是 HTTPS（GitHub Pages 默认就是）。

**添加成功但里面没有插件**
- 看 `Release` 里的 `Architectures` 是否包含你设备的架构：rootless（Dopamine / palera1n）
  是 `iphoneos-arm64`，用 Theos 打包时记得 `THEOS_PACKAGE_SCHEME = rootless`。
- 看 `Packages` 里 `Filename: ./debs/xxx.deb` 指向的文件在仓库里真的存在。
- 别忘了 push 之后在 Sileo 里下拉刷新。

**安装时报 hash mismatch**
- 说明 `.deb` 被改动过但索引没重建。重新 `python tools/gen_repo.py` 并推上去。

**`control` 里的字段要求**
- `Package` / `Version` / `Architecture` / `Description` 必须有；
- 不要手写 `Installed-Size`（脚本会自动算，重复会让 dpkg 报错）；
- 想显示自定义图标，加 `Icon: https://.../icon.png`；
- 想显示详情页，加 `Depiction:` 或 `Sileodepiction: https://...`。

**GitHub 限制**
- 单个文件 ≤ 100 MB，Pages 站点建议 ≤ 1 GB。tweak 的 deb 一般只有几十 KB，完全够用。

---

## 换源名 / 换地址

改 `repo.json`：

| 字段 | 说明 |
| --- | --- |
| `origin` / `label` / `name` | 源名称，Sileo 里显示的名字（当前是 `vv`） |
| `description` | 源简介 |
| `maintainer` | 维护者，会作为包的默认维护者 |
| `url` | **源地址**，必须以 `/` 结尾 |
| `accent` | 落地页主色调 |
| `architectures` | 设备架构，`iphoneos-arm64`（rootless）/ `iphoneos-arm`（老越狱） |

也可以命令行一把改掉（会自动补结尾的 `/`）：

```bash
python tools/gen_repo.py --url https://fatekingcsr.github.io/vv/
```

## 用自定义域名

在仓库根目录加一个 `CNAME` 文件（内容就是你的域名，例如 `repo.example.com`），
在域名服务商加一条 CNAME 记录指向 `fatekingcsr.github.io`，然后在
**Settings → Pages → Custom domain** 里填上域名并开启 HTTPS。
最后把 `repo.json` 的 `url` 改成 `https://repo.example.com/` 并重新生成索引。
