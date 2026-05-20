# Lecture Summary Prompt

Use this prompt for long-form courses, lectures, livestream replays, workshops, and training videos.

Input:
- title
- source URL or local file path
- author
- duration
- transcript or timed transcript
- optional draft summary

Output in Simplified Chinese. Produce clean course notes, not a short-video highlight summary.

```markdown
# 课程精校笔记：{title}

## 元信息
- 来源：{url_or_path}
- 作者：{author}
- 时长：{duration}
- 文稿来源：{subtitle_or_transcription}

## 课程定位
用 1 段话说明这节课解决什么问题、属于什么模块、学习后应该掌握什么。

## 核心框架
- 用 3-6 条 bullet 总结本课主框架。
- 每条必须是概念化表达，不要逐字摘抄口语。

## 关键概念
- **概念**：结合课程语境解释，说明作用和边界。

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
    课程定位
    核心框架
    关键概念
    实操方法
    常见误区
    复习问题
```

---

## 整理后逐字稿
保留原文结构，可修正明显 ASR 错字；不要删除重要论证。
```

Rules:
- Prefer course-note structure over entertainment-style highlights.
- Remove filler words such as "对吧", "然后", "就是说" unless needed for meaning.
- Fix obvious ASR mistakes when context is clear, such as 邀约, 暧昧, 聊骚.
- Keep claims grounded in the transcript.
- If timestamps are uncertain, use approximate section timestamps from the transcript.
