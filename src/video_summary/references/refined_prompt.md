# Refined Summary Prompt

Use this prompt when a high-quality semantic rewrite is needed after transcript extraction.

Input:
- video title
- source URL
- author
- duration
- transcript or timed transcript

Output in Simplified Chinese:

```markdown
# 视频精校总结：{title}

## 元信息
- 来源：{url}
- 作者：{author}
- 时长：{duration}
- 文稿来源：{subtitle_or_transcription}
- 分析范围：仅基于字幕/音频转写，不包含 OCR、截图或画面理解。

## 摘要
用 1 段话概括视频主张、论证路径、关键结论。避免逐字摘抄，改写成清晰书面语。

### 亮点
- 5 条高信息密度要点，每条包含观点和意义。如果有时间戳，末尾加 `[mm:ss]`。

### 思考
1. **提出一个能检验理解的问题？**
   - 给出基于视频内容的回答。
2. **提出一个实践判断问题？**
   - 给出可操作的判断标准。

### 术语解释
- **术语**：结合视频语境解释，不写泛泛定义。

---

## 视频章节总结 ｜ {one_sentence_title}

先用 1 段话说明整条视频的结构。

### [mm:ss] - 章节标题
用 1 段话总结本章论点、例子和结论。

---

## 思维导图

```mermaid
mindmap
  root(({short_title}))
    核心主张
    关键论证
    实践方法
    风险误区
    术语
```

```

交付约束：
- transcript 仅作分析依据，不是最终稿内容。
- 最终稿不得包含完整逐字稿、全文转录或“整理后逐字稿”章节。
- 只允许为说明关键观点引用 1-3 句原话，其余内容必须改写为精修总结。

Rules:
- Keep the author's original stance separate from your own judgment.
- Do not invent examples, timestamps, or claims not supported by the transcript.
- Fix obvious ASR errors only when context is clear.
- Prefer concise, precise chapter titles over decorative titles.
