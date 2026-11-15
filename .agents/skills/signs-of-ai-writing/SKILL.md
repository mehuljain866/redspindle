---
name: signs-of-ai-writing
description: >-
  Identifies, removes, and prevents stylistic patterns, structural formulas, and vocabulary typical of
  unprocessed LLM text (based on Wikipedia:Signs of AI writing / WP:AISIGNS). Use when drafting, editing,
  or reviewing documentation, READMEs, articles, or messages to ensure natural, direct, human prose.
---

# Signs of AI Writing (WP:AISIGNS Guide)

This skill provides an editorial framework to detect and eliminate writing artifacts commonly produced by Large Language Models (LLMs). It is modeled on Wikipedia's community guide [Wikipedia:Signs of AI writing (WP:AISIGNS)](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing).

The goal is not to sound artificially casual, but to produce direct, grounded, factual prose that conveys information without puffery, superficial transitions, or robotic symmetry.

---

## 1. Core Content & Editorial Tone Red Flags

### A. Undue Emphasis on Significance and Legacy (`WP:AILEGACY`)
LLMs habitually inflate routine technical features or events into historical milestones.
* **AI Pattern**: "The introduction of X marked a pivotal shift in the landscape of Y, serving as a lasting testament to..."
* **Fix**: State what the feature does plainly. Do not lecture the reader on its philosophical importance.
* **Avoid**: *pivotal moment, paradigm shift, landmark development, testament to, serves as a beacon, broader tapestry*.

### B. Promotional Language and Marketing Hype (`WP:AIPROMO`)
LLMs default to uncritical praise and marketing brochure language.
* **AI Pattern**: "A powerful, cutting-edge solution engineered to seamlessly empower users with a comprehensive suite of tools..."
* **Fix**: Use precise technical verbs and nouns. Replace adjectives with observable capabilities.
* **Avoid**: *cutting-edge, game-changing, groundbreaking, seamless, vibrant, bespoke, elevate, empower, harness the power of*.

### C. Negative Parallelisms & Formulaic Balance (`WP:AIBALANCE`)
LLMs rely heavily on symmetrical "not X, but Y" or "rather than simply A, it B" constructions.
* **AI Pattern**: "Rather than merely downloading files, the system actively curates..." or "Not only does it support MP3, but it also enables FLAC..."
* **Fix**: Say what it does directly. "The system downloads files and curates tracklists." or "Supports MP3 and FLAC."

### D. Superficial Summaries & Vague Attributions (`WP:AISPECIFIC`)
LLMs generate broad generalities when they lack concrete details, or attribute claims to nameless groups.
* **AI Pattern**: "Many users and experts agree that maintaining audio quality is essential in modern workflows."
* **Fix**: Name specific tools, standards, or facts. "MP3 files below 192 kbps discard high frequencies above 16 kHz."

---

## 2. Vocabulary & Cliché Blacklist

When reviewing drafts, scan for and remove these telltale words and filler phrases:

| Category | Words & Phrases to Avoid | Better Alternatives |
| :--- | :--- | :--- |
| **Puffery Verbs** | *delve, underscore, foster, encapsulate, showcase, boast, harness, elevate, transcend* | *use, show, include, support, build, write, run* |
| **Inflated Nouns** | *testament, tapestry, beacon, realm, landscape, paradigm, synergy, facet, interplay* | *system, tool, field, area, feature, part* |
| **Intense Adjectives** | *pivotal, crucial, vibrant, meticulous, profound, paramount, bespoke, seamless* | *important, necessary, detailed, clear, direct* (or omit) |
| **Filler Transitions** | *Furthermore, Moreover, It is worth noting that, Needless to say, In essence* | (Delete the transition entirely; start with the subject) |
| **Conclusory Wrappers** | *Ultimately, In conclusion, All in all, To summarize* | (State the final fact directly without announcing the conclusion) |

---

## 3. Structural & Formatting Tells

### A. The Three-Sentence Formula
LLM paragraphs often follow a mechanical rhythm:
1. Broad introductory assertion.
2. Symmetrical elaboration with a negative parallelism ("While X does Y, Z ensures W...").
3. Wrap-up sentence reaffirming broader importance.
* **Correction**: Break the rhythm. Vary sentence length. Lead with facts or actionable instructions.

### B. Bullet Point Symmetries
LLMs frequently format lists with identical structure:
* **Bold Title (Colon)**: Two lines of text starting with an active verb and ending with a generic benefit.
* **Bold Title (Colon)**: Two lines of text starting with an active verb and ending with a generic benefit.
* **Correction**: Vary bullet formatting. Some points only need a single phrase; others need a short code snippet or specification.

### C. Em Dash Overuse
LLMs use em dashes (`—`) far more frequently than human technical writers to insert explanatory clauses.
* **Correction**: Use standard punctuation (commas, parentheses, or separate sentences).

---

## 4. Editing Walkthrough & Checklist

When drafting or editing any text:
1. **Strip empty adjectives**: Remove *seamless, comprehensive, powerful, robust, intuitive*.
2. **Cut filler preambles**: Delete *It is important to remember that*, *As mentioned earlier*, *In today's digital landscape*.
3. **Verify standards & neutrality**: Do not present open standards (such as `.lrc` or ID3 tags) as proprietary to one company or platform.
4. **Be concrete**: Replace vague promises ("high quality") with specifications ("320 kbps CBR MP3, 44.1 kHz").
5. **Read aloud**: If a sentence sounds like a corporate press release or a high school essay striving for word count, rewrite it plainly.
