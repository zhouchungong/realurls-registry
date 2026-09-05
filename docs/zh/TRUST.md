# TRUST.md —— 我们凭什么可信

> 中文镜像，供参考；**以仓库根目录的[英文版](../../TRUST.md)为准**（[英文版](../../TRUST.md)随代码同步更新，本页可能滞后）。


这是本项目最重要的文件。realurls 唯一的产品是**信任**，而信任的定义必须先于实现。

如果你只读一个文件，读这个。

---

## 1. 我们断言什么

**只有一件事：某个域名是否由某个组织控制。**

```
realurls 说 "anthropic.com 属于 Anthropic" 的意思是：
  存在若干条独立的、可被任何人复现的机器证据，共同支持这一归属关系。
```

仅此而已。

## 2. 我们**不**断言什么

这一节和上一节同等重要。以下内容我们**一概不做判断**，请勿据此决策：

| 我们不说 | 请找谁 |
|---|---|
| 这个网站安全吗 | Google Safe Browsing、VirusTotal、你的杀毒软件 |
| 这个网站是不是钓鱼/诈骗 | 同上。**我们不维护黑名单**（见 §6） |
| 这家公司靠不靠谱、产品好不好 | 不在我们的能力范围 |
| 这个下载文件有没有毒 | 杀毒软件、沙箱 |
| 这个域名合不合法、有没有侵权 | 法院、商标局、域名争议解决机构 |

**一个域名被我们标为 `verified`，只意味着"它确实是那家公司的"，不意味着"它是安全的"。** 一个公司的官网被黑客入侵后，它依然是那家公司的官网。

## 3. 五档状态与它们的确切含义

| 状态 | 含义 | API 会怎么回答 |
|---|---|---|
| `verified` | 证据充分：≥1 条独立锚点 + ≥2 条独立佐证 | **唯一会给出肯定答复的状态** |
| `provisional` | 有锚点但佐证不足，21 天公示期 | 「证据不足」+ 列出已有证据 |
| `community` | 只有佐证，无锚点 | 「证据不足」 |
| `unverified` | 未达门槛 / 域名太新 / 尚未审查 | 「不知道」 |
| `stale` | 曾经 verified，但超过 TTL 未重验 | 「不知道」—— 过期数据**自动失效** |
| `review_required` | 关键属性突变（可能被抢注或劫持） | 「不知道」 |
| `disputed` | 与另一条 verified 断言冲突 | 「存在争议」+ 列出双方证据 |
| `flagged` | 已被安全情报标记 | 「不给出归属判定」（转引来源） |

**核心承诺：宁可说「不知道」，绝不说错。**
我们的 recall 会很难看 —— 大量域名长期停在 `unverified`。这是刻意的取舍。一个信任源说错一次的代价，远大于说不知道一千次。

## 4. 如何独立复现我们的每一条判定

这是我们与「某个人整理的清单」的根本区别：**你不需要相信我们，你可以自己验一遍。**

每个实体页与 `entities/**.yaml` 都列出了完整证据。以 `anthropic.com` 为例：

```bash
# A1 —— GitHub 组织已通过域名验证
curl -s https://api.github.com/orgs/anthropics | jq '{name, blog, is_verified}'
# 期望: {"name":"Anthropic","blog":"https://anthropic.com","is_verified":true}

# A3 —— 企业注册指纹
curl -sL https://rdap.org/domain/anthropic.com \
  | jq '{registrar: [.entities[]|select(.roles[]=="registrar")|.vcardArray[1][1][3]],
         events: [.events[]|{(.eventAction): .eventDate}], status}'
# 期望: MarkMonitor Inc. / registration 2001-10-02 / expiration 2033-10-02 / 三把 client*Prohibited 锁

# B1 —— Wikidata P856
curl -s "https://www.wikidata.org/w/api.php?action=wbgetclaims&entity=Q116758847&property=P856&format=json"

# B4 —— Wayback 连续性
curl -s "http://web.archive.org/cdx/search/cdx?url=anthropic.com&limit=1&output=json"
```

然后把证据喂给定案引擎，你会得到和我们一样的结论：

```bash
python -m src.verify anthropic.com          # 采集 + 判定，打印完整证据链
python -m pytest tests -q                   # 跑我们全部的正/负样本回归
```

**定案规则就是代码本身**（`src/policy.py`），不是某个人的主观判断。规则的任何变更都必须经过 CODEOWNERS 双人审批，并留在 git 历史里。

## 5. 数据从哪来，谁能改

```
社区提交 → Issue Form（只提交「线索」）
        → 机器人自动跑全套证据采集
        → 证据充分：机器人开 PR，人类只做 review
        → 证据不足：自动关闭，并告诉你缺哪条
```

**人类永远不能直接编辑 `entities/` 里的数据。** 所有数据由流水线生成。

每条 `verified` 记录背后有两道审计：每次发布前固定规模的人工抽样，以及逐条阅读证据、寻找矛盾的 AI 复核。AI 复核是单向的——它只能把记录降为 `review_required`（并保持到人工清除），不能把任何记录升级。见 [POLICY.md §3](POLICY.md#3-精度约束)。

这不是流程洁癖 —— 如果 JSON 可以被 PR 直接改，那么本仓库就是黑产洗白钓鱼站的最高价值目标，而「精心构造的 PR 骗过疲惫的 reviewer」是必然会发生的事。**把人从数据写入路径上移开，是唯一可靠的防御。**

## 6. 我们不维护黑名单

`non_affiliated` 字段里记录的「与某实体无关联的相似域名」，其性质是：

- **客观信号的罗列**（注册 11 天、编辑距离为 3、被 Google Safe Browsing 标记），**不是定性**。
- 我们不使用「钓鱼」「诈骗」「恶意」这类词汇描述任何域名。定性属于有资质的安全厂商与执法机构。
- 我们**不镜像任何第三方黑名单**。原因有三：许可证不允许（OpenPhish 禁止再分发，GSB 条款禁止转发布）；钓鱼域名寿命以小时计，镜像一份陈旧名单等于用我们的名义指控一个可能已经无辜的域名；以及我们不愿继承别人的误判和责任。

我们只在判定时**即时查询**这些源作为否决信号，查完即弃。

## 6a. 我们记录什么

每次查询只保留一个聚合计数：日期、查询键（域名或名称，小写）、我们给出的判定。**不记 IP、不记 User-Agent、不记会话、不记比"天"更细的时间。** 看起来像个人数据的键（含 `@`，或一长串不透明 token）在计数前丢弃。聚合结果在 `api.realurls.org/v1/demand` 公开，最低 3 次才会出现，罕见查询永远不会露出。用途只有一个：让流水线优先处理人们真正在问、而我们还答不上来的东西。

## 7. 我们会犯错，以及犯错之后

我们一定会有错误。承诺如下：

1. **争议通道**：在本仓库提 Issue（`dispute` 模板），或发信到 `dispute@realurls.org`。
2. **响应 SLA**：`verified` 状态的争议，**48 小时内**降级为 `disputed` 并暂停 API 肯定答复 —— 先止损，再查证。举证责任在我们，不在你。
3. **域名所有者优先**：如果你是域名的实际控制者，通过 DNS TXT 自证（A5）即可覆盖我们的任何判定。**你对自己的域名有最终解释权。**
4. **公开更正**：所有错误更正保留在 git 历史与 `CORRECTIONS.md` 中，永不静默删除。一个隐藏自己错误记录的信任源不值得信任。

## 8. 我们自己的完整性

一个「真官网」数据库如果自己被篡改，危害比它解决的问题更大。因此：

- 每次 release 用 **sigstore/cosign 签名**，API 返回体带数据集版本号与内容哈希。
- 所有 GitHub Actions **pin 到 commit SHA**，防 action 供应链投毒。
- 分支保护 + 强制 2FA + `CODEOWNERS` 双人审批。
- 数据变更是 **append-only 的 git 历史**，任何一条 verified 记录的全部历史可追溯。

详见 [SECURITY.md](SECURITY.md)。

## 9. 利益冲突声明

- **查询永久免费，数据永久开放**（`entities/` 与 `dist/` 采用 CC BY-SA 4.0）。
- **官网链接永远是裸链**：无跳转、无跟踪参数、无 affiliate。
- 本项目**当前不接受任何形式的付费收录、付费排序或赞助展示**。若未来引入商业模式，将在此处明确公示，且**付费永远不能影响任何一条 `verified` 判定**。
- 若你发现我们违反了以上任何一条，请公开地骂我们。这是应该的。

---

*本文件的任何变更都会记录在 git 历史中。最后更新：见 `git log TRUST.md`。*
