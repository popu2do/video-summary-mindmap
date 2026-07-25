# Lecture Summary Prompt

Use this prompt for long-form {content_label} material such as courses, lectures, workshops, training videos, or structured documents.

Input:
- title
- source URL or local file path
- author
- duration
- extracted text or timed transcript
- optional draft summary

Output in Simplified Chinese. Produce clean {content_label} notes, not a short-form highlight summary.

```markdown
# {content_label}精校笔记：{title}

## 元信息
- 来源：{url_or_path}
- 作者：{author}
- 时长：{duration}
- 文稿来源：{subtitle_or_transcription}
- 分析范围：{analysis_scope_zh}

## {content_label}定位
用 1 段话说明这份{content_label}材料解决什么问题、属于什么模块、阅读后应该掌握什么。

## 核心框架
- 用 3-6 条 bullet 总结材料主框架。
- 每条必须是概念化表达，不要逐字摘抄口语。

## 关键概念
- **概念**：结合{content_label}语境解释，说明作用和边界。

## 分阶段讲解

### [mm:ss] - 阶段标题
总结该阶段的主论点、论证方式、例子、结论。

## 实操方法
1. 可执行步骤。
2. 判断标准。
3. 复盘方式。

## 常见误区
- 误区：为什么错；应该怎么修正。

## 复习问题
1. **问题？**
   - 答案。

## 思维导图

```mermaid
mindmap
  root(({short_title}))
    {content_label}定位
    核心框架
    关键概念
    实操方法
    常见误区
    复习问题
```

```

交付约束：
- transcript 仅作分析依据，不是最终稿内容。
- 提取文本仅作分析依据，不是最终稿内容。
- 最终稿不得包含完整逐字稿、全文转录或“整理后逐字稿”章节。
- 只允许为说明关键观点引用 1-3 句原话，其余内容必须改写为精校笔记。

Rules:
- Prefer structured notes over entertainment-style highlights.
- Remove filler words unless needed for meaning.
- Fix obvious extraction or ASR errors when context is clear.
- Keep claims grounded in the source text.
- If timestamps are uncertain, use approximate section timestamps from the source.
