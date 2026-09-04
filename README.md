# realurls / registry

**一个「域名 ↔ 组织」的开放归属证据库。每条断言都由可复现的机器证据支撑，通过 MCP / API 直接进入 AI 的调用路径。**

> 不判定安全，只判定归属。宁可说「不知道」，绝不说错。

---

## 这是什么

AI 与搜索引擎越来越多地替人回答「XX 的官网是哪个」「从哪下载 XX」。而 2026 年已有多起公开事故：SEO 投毒的假下载站被推到搜索首位（Black Cat 战役感染约 27.8 万台设备），专门仿冒 Claude Code / Gemini CLI 官网的战役被安全厂商记录在案，微软亦确认过用户询问 LLM 下载地址后被引导至攻击者域名的实例。

问题的根源是：**没有一个开放、可编程、带证据链的「官网归属真值源」。**

黑名单侧早已饱和（PhishTank、Phishing.Database、openSquat……），但它们回答的是「这个域名坏不坏」，而不是「这个域名属于谁」。realurls 补的是后者。

## 与「某个人整理的清单」有什么不同

清单说「相信我，这是官网」。我们说「这里有 5 条独立证据，命令都给你了，你自己验」。

```bash
# 我们凭什么说 anthropic.com 属于 Anthropic —— 你可以自己跑一遍
curl -s https://api.github.com/orgs/anthropics | jq '{name, blog, is_verified}'
# {"name":"Anthropic","blog":"https://anthropic.com","is_verified":true}
#  ↑ GitHub 已经代做了 DNS 级域名控制权验证
```

完整的信任模型见 **[TRUST.md](TRUST.md)**，定案规则见 **[POLICY.md](POLICY.md)**。

## 现在的状态

**M1 —— 采集流水线已跑通。** 尚未开始批量冷启动。

```
✅ M0  TRUST.md / POLICY.md / policy.py / 正负样本回归测试
✅ M1  证据采集流水线 + `python -m src.verify <domain>` 端到端跑通
⬜ M2  冷启动数据 ≥1,200 verified，抽样 precision ≥99.5%
⬜ M3  Cloudflare Workers API + MCP Server（发布点）
⬜ M4  realurls.com 证据页 + 浏览器扩展 + 生态回写
```

首发品类：**AI 与开发者工具**，目标约 1,500 个组织 / 4,000 个域名。

## 快速开始

```bash
pip install -e ".[dev]"

# 本项目不依赖任何 pytest 插件。若你的环境里装了会崩的第三方插件，加上这个环境变量隔离：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests -q

python -m src.validate      # 校验 entities/：schema + 状态复算 + 中性措辞 + 唯一性

# 端到端验证一个域名，打印完整证据链与复现命令
python -m src.verify anthropic.com
python -m src.verify claude.ai --anchor anthropic.com     # 锚点扩散
```

```python
from src.policy import DomainFacts, Evidence, decide

d = decide(
    DomainFacts(domain="anthropic.com", age_days=9104),
    [
        Evidence("A1", {"org_verified": True, "blog": "https://anthropic.com"}),
        Evidence("A3", {"registrar": "MarkMonitor Inc.", "remaining_days": 2584,
                        "locks": ["delete", "transfer", "update"]}),
        Evidence("B1"),
        Evidence("B4", {"history_days": 1800}),
    ],
)
print(d.status, d.confidence, d.reasons)
# verified 0.9303 ['2 条独立锚点 + 2 条独立佐证，达到 verified 门槛']
```

## 仓库结构

```
TRUST.md              ← 先读这个：我们验证什么、不验证什么、如何复现、如何质疑
POLICY.md             ← 定案规则的人类可读版
SECURITY.md           ← 含仓库自身的威胁模型
entities/             ← 数据（YAML，一实体一文件）。人类不能直接编辑，只由流水线生成
candidates/           ← 机器自动产出的待验证条目，不进 API
src/policy.py         ← 定案引擎：项目唯一的真理来源
tests/                ← 正样本 + 负样本回归语料
```

## 贡献

**你贡献的是「线索」，不是「数据」。** 通过 [Issue 模板](.github/ISSUE_TEMPLATE/submit-domain.yml) 提交，机器人会自动采集证据并决定是否收录。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

如果你是某域名的实际控制者，DNS TXT 自证（A5）可以覆盖我们的任何判定。

## 许可

- 数据（`entities/`、`dist/`）：**CC BY-SA 4.0**
- 代码（`src/`、`tests/`）：**MIT**

## 免责声明

realurls 只判定**域名归属**。我们不判定网站的安全性、合法性或产品质量。
一个被标为 `verified` 的域名，只意味着它确实属于该组织 —— 不意味着它是安全的。
安全性判断请以 Google Safe Browsing、VirusTotal 等有资质的安全厂商为准。
