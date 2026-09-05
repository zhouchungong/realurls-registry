# POLICY.md —— 定案规则

本文件是 [`src/policy.py`](src/policy.py) 的人类可读镜像。
**两者若有出入，以代码为准**，并请提 Issue 告诉我们文档过期了。

---

## 0. 先锚定实体，再验证域名

**控制权 ≠ 身份。** A1（GitHub 组织已验证域名）、A2（包 provenance）、A5（DNS 自证）证明的都是
「某个主体控制这个域名」，而不是「这个域名属于实体 X」。攻击者完全可以为 `claude-desktop.io`
建一个叫 "Claude" 的组织并验证它——控制权是真的，身份是假的。
（评审时构造过这条链，修复前被判 verified 0.85，见 `tests/negative_corpus.yaml` 的 `attacker-controlled-verified-org`。）

所以判定分两个阶段：

```
阶段 1  实体锚定（src/anchor.py）
        从独立权威确立实体的 canonical 标识，两种权威任一即可：
          ① Wikidata 条目（P856 指向本域名、类型 ∈ 组织/企业/软件/网站、站点链接 ≥ 3）
             → canonical GitHub 组织 = 该条目的 P2037 或 P1324；canonical Wikidata = QID
          ② GitHub 项目史：组织拥有一个 非 fork、创建 ≥3 年、≥300 贡献者、≥5k 星 的仓库
             → canonical GitHub 组织 = 该组织；仓库全名进 canonical.sources 供核对
        展示名（names.en）：Wikidata 标签优先；否则用 GitHub 组织显示名——那是自填字段，只用于
        展示、不参与任何判定，且在 provenance.label_source 里如实标注 self-declared
        或由人工审核指定（来源记为 human:*，随实体记录落盘供 reviewer 核对）

阶段 2  域名验证（src/policy.py）
        A1 / A2 只有在组织 == canonical GitHub 组织时才算数
        B1     只有在 QID  == canonical Wikidata 时才算数
```

**锚定失败的实体最多 provisional。** 一个在 Wikidata、应用商店、npm 都查无此人的"公司"，我们凭什么替它背书。
门槛用站点链接数而非条目存在性：建一个 Wikidata 条目零成本，让三种语言的 Wikipedia 都为你写文章不是。

**为什么要有权威 ②**：220 条真实分布摸底，Wikidata 只能锚定 17%——它覆盖公司，不覆盖开源项目，
而首发品类一半是开源项目。项目史是另一种攻击者买不到的东西：星可以刷，但 3 年前就开始、
300 个不同的人来提交，刷不出来；把别人的历史 push 进新仓库，`created_at` 会暴露；fork 会继承
上游贡献者，所以必须排除 fork。摸底样本里 openclaw.ai（0.8 年，38 万星）、career-ops.org
（0.3 年，7 万星、356 贡献者）这类流星项目，正是年龄门槛存在的理由——**只看星数会出事**。

锚点扩散（A6）场景下，目标域名**继承锚点域名的实体**：claude.ai 属于 Anthropic（Q116758847），
而不是属于"Claude"这个产品条目。

## 1. 证据分级

### 1.1 锚点证据（Tier A）—— 至少需要 1 条

锚点回答的是「谁控制这个域名」，具备**强不可伪造性或强成本壁垒**。

| 代号 | 证据 | 权重 | 有效性条件 |
|---|---|---|---|
| **A5** | DNS TXT 自证 `_realurls.<domain>` | 0.90 | token 匹配 |
| **A1** | GitHub 组织已验证域名 | 0.80 | `is_verified == true` 且 `blog` 的可注册域 == 目标域 **且 org == canonical GitHub 组织** |
| **A7** | 受限政府 TLD | 0.80 | 后缀 ∈ `.gov` `.gov.uk` `.gov.cn` `.gouv.fr` `.go.jp` … （注册局仅允许政府机构注册；只证明"是政府站"，不证明"是哪个部门"） |
| **A2** | 包 provenance → 仓库 → 已验证组织 | 0.75 | provenance 通过验证 **且** 链末端组织已验证 **且** 其 blog 域匹配 **且 链末端 == canonical GitHub 组织** |
| **A4** | 证书 Subject `O=` | 0.70 | 证书为 **OV/EV** 且 `O=` 非空 |
| **A6** | 锚点扩散 | 0.65 | 源域名自身 `verified` **且 源域名页面链接到本域名（一方声明）** **且** ≥1 条结构性关联；仅靠 `cert_san` 时 SAN 数 ≤ 25 |
| **A8** | 已锚定仓库的 homepage → 本域名 | 0.60 | 仓库通过项目史门槛 **且** org == canonical **且** homepage 可注册域 == 本域名 **且** 本域名首页反向链回该组织 **且** 本域名不是平台域（discord.gg / x.com / github.io …） |
| **A3** | 企业注册指纹 | 0.55 | **品牌保护类**注册商 **且** 剩余期 ≥1095 天 **且** 注册局锁 ≥2 把 **且** 域龄 ≥730 天 |

**A8 为什么权重低于 A1**：A1 有 GitHub 代做的 DNS 级控制权验证，A8 只有仓库元数据。但对「组织没做域名验证」
的开源项目（摸底里占 60%），A8 是唯一能把域名绑到已锚定身份上的证据。平台域排除是实测教训：yt-dlp 的
homepage 字段填的是 discord.gg。反向链接要求防的是域名易主：仓库还指着旧域名，但旧域名已经不链回仓库了。

**A6 为什么两个条件缺一不可**：只有结构性关联——Cloudflare 等从共享池分配 NS，攻击者反复建账号能碰到同一对；
只有一方声明——已 verified 域名的页脚里也有 linkedin.com / x.com，那不是自家资产。
攻击者要同时做到「让 anthropic.com 首页链接到我」和「NS 碰撞」，前者做不到。

**A3 的注册商名单只含品牌保护类**（MarkMonitor、CSC、Com Laude、Safenames、Nom-IQ、IP Mirror、GoDaddy Corporate 等）。
评审时剔除了 Amazon Registrar（Route53，任何人 12 美元/年）、Google LLC、InterNetX、Ascio 等零售/批发商。

**为什么 A3 权重最低**：企业注册指纹只证明对方「买得起」（企业级注册商年费数百美元且需企业实名），是**成本壁垒**而非**身份证明**。它能挡住 99% 的黑产，但挡不住有预算的定向攻击。

**A2 的信任锚要说清楚**：我们目前**不做 sigstore 签名的密码学验证**。做的是通过 TLS 向
`registry.npmjs.org` 索取 attestation，解出其中 in-toto 声明的源仓库。因此 A2 的信任锚是
「npm registry 的 TLS + npm 对发布流程的把关」，与 A1 的信任锚（`api.github.com` 的 TLS +
GitHub 的域名验证）**是同一量级，而非密码学证明**。补上真正的签名验证是明确的加固项，
但它不改变当前的信任层级——能伪造 npm registry HTTPS 响应的攻击者，同样能伪造 GitHub API 响应。

**为什么 A1 权重这么高**：`is_verified == true` 意味着 GitHub 已经代我们完成了 DNS 级别的域名控制权验证。这是免费搭上的一条强证据链，且对「AI / 开发者工具」这个首发品类覆盖率极高。

### 1.2 佐证证据（Tier B）—— verified 需要 ≥2 条

佐证本身不能证明控制权，但能证明「这个域名在多个独立权威处被公认为该实体的官网」。

| 代号 | 证据 | 权重 | 有效性条件 |
|---|---|---|---|
| B1 | Wikidata P856 | 0.12 | 实体类型 ∈ 组织/企业/软件/网站（`P31/P279*`）**且 QID == canonical Wikidata** |
| B4 | Wayback 首次快照 + 连续性 | 0.12 | 历史跨度 ≥365 天 |
| B3 | 应用商店开发者官网字段 | 0.10 | — |
| B6 | 官方社媒公示链接 | 0.10 | — |
| B2 | 包管理器 homepage / repository | 0.08 | — |
| B5 | Tranco / Radar 排名 | 0.06 | 排名 ≤1,000,000 |
| B7 | Google Safe Browsing 无记录 | 0.05 | 未被标记（被标记则**不能**作为正向佐证） |

**B1 为什么要限定实体类型**：Wikidata 任何人可编辑，往某条目加一条 P856 指向钓鱼域名的成本为零。
实测中我们的第一版查询在 `claude.ai` 上取回了一个标题是中文报纸标题的垃圾条目（Q116755258）。
不做类型过滤，B1 就是一条可被任意人凭空制造的「佐证」。见 SECURITY.md T7。

### 1.3 证据独立性（容易被忽略但很关键）

**三条互相推导出来的证据，不等于三条独立证据。**

- **A1 / A2 / A8 合并计数**：三者都落在「同一个 GitHub 组织」这个信任锚上，组织被接管一起失效，只取权重较高者。
- **A2 蕴含 B2**：provenance 已经比 `homepage` 字段强得多，B2 不再重复计数。

规则见 `CORRELATED_ANCHOR_GROUPS` 与 `IMPLIED_CORROBORATIONS`。

---

## 2. 判定流程

```
① 硬性否决（任何证据都无法推翻）
   ├── Safe Browsing 标记 或 VirusTotal ≥2 引擎判恶意  → flagged
   ├── 与另一条 verified 断言冲突                      → disputed
   └── 关键属性突变（NS/A/注册商/到期日/组织状态）     → review_required

② 数据保鲜
   └── previous_status == verified 且超过 TTL(默认 30 天) → stale

③ 证据校验 → 剔除无效证据 → 合并关联证据

④ 新域名门槛（未知按最坏情况处理）
   ├── 域龄 < 180 天 且 无 A5                          → unverified
   └── 域龄未知 且 无 A5/A7                            → 最多 provisional
       （rdap.org 对 .de/.io/.cn/.so/.ch/.jp 等大量 ccTLD 返回 404。
         流水线会用 Wayback 首次快照作为域龄**下界**兜底——一个域名不可能
         比它的第一次快照更年轻；兜底也失败才算未知。）

⑤ 定案
   ├── 锚点 ≥1 且 佐证 ≥2  → verified
   ├── 锚点 ≥1             → provisional（公示 21 天）
   ├── 佐证 ≥3             → community
   └── 其余                → unverified
```

**每一条被剔除的证据都必须附带原因**，并原样出现在 API 返回与实体页上。可解释性是对外承诺的一部分，不是调试功能。

### 2.1 置信度

独立证据近似合成：`confidence = 1 - Π(1 - w)`。

`provisional` 上限 0.75，`community` 上限 0.50，`unverified` 上限 0.30，硬性否决恒为 0。
**置信度只用于排序与展示，不参与定案** —— 定案完全由上面的计数规则决定。这是刻意的：一个可被"堆量刷分"的加权模型，迟早会被黑产反向工程后刷过阈值。

---

## 3. 精度约束

**precision ≥ 99.5%** 是本项目唯一不可妥协的指标。覆盖量是软目标。

保障手段：

1. **负样本回归**（`tests/negative_corpus.yaml`）—— 每条都断言 `!= verified`。任何一条变绿都是 P0 事故。
2. **人工抽样审计** —— 每次数据集发布前抽 200 条 `verified` 人工复核。低于 99.5% 则回退规则，不许发布。
3. **每修一个误报，必须往负样本语料里加一条对应用例。**

---

## 4. 修改本策略的流程

`src/policy.py` 中的阈值与权重，**任何一处改动都等于改动本项目对外的信任承诺**。因此：

1. 必须同步修改本文件；
2. 必须经过 `CODEOWNERS` 双人审批；
3. 必须跑全量负样本回归 + 对现有数据集做 diff，说明本次改动会让多少条记录升级/降级；
4. 变更理由写进 commit message，永久留在 git 历史里。

**降低门槛的改动（让更多东西变成 verified）需要格外谨慎** —— 这正是攻击者最想让我们做的事。
