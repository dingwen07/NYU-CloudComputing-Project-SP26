"""Prompt templates for LLM-based knowledge processing."""

SYSTEM_PROMPT = """You are a knowledge management assistant. Your job is to analyze documents \
and extract structured metadata. Always respond with valid JSON only, no markdown fences."""

ANALYSIS_PROMPT = """Analyze the following document content and produce structured metadata.

Submitted title, if any:
---
{title}
---

Document content:
---
{content}
---

Respond with a JSON object containing:
{{
    "suggested_title": "A clear, specific title for this document. Improve the submitted title if one was provided.",
    "summary": "A concise 2-3 sentence summary of the document",
    "tags": ["list", "of", "relevant", "tags"],
    "category": "One of: research, tutorial, reference, opinion, dataset, code, other",
    "key_concepts": ["list", "of", "key", "concepts", "or", "topics"]
}}

Respond with valid JSON only."""
