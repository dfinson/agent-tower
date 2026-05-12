# Semantic TOC Design: LLM-Based Activity Boundaries

## Problem Statement

The current activity boundary system fails in two ways:
1. **Over-segments** via deterministic plan-step transitions (a plan step ≠ a meaningful section)
2. **Under-segments** via LLM stickiness (the model never fires `new_activity: true` because the question framing biases toward continuation)

The root cause: the current prompt asks "is this a NEW activity?" in isolation, showing only step titles. The LLM has no linguistic context to detect shifts — it can't see the *contrast* between what the agent was doing and what it's now doing.

## Data-Backed Findings

Analysis of 35 real jobs (174k events, 268 jobs total in production DB):

| Signal | Reliability | Notes |
|--------|------------|-------|
| Agent message first-line contrast | **HIGH** | 4/5 ideal boundaries show obvious linguistic shift |
| Plan step transitions | MEDIUM | Over-segment long steps, under-segment multi-step flows |
| File overlap / directory clustering | LOW | 28% of turns have zero file overlap; too noisy |
| Phase-mode classification | LOW | 2.1:1 transition-to-boundary ratio; too many false positives |
| Intent field (when no agent message) | MEDIUM | 54% of research job turns lack agent_message; intent fills the gap |
| First file write after long read streak | **HIGH** | Always a boundary in research/audit jobs |

**Ideal section ratio**: 10–18 turns per section (verified across 8 jobs of varying length).

**Key insight**: Boundaries are detectable when the LLM can see the *trajectory* (recent turns) and the *current state* in the same frame. The contrast makes the decision obvious. A 3-turn window is sufficient.

## Design

### Core Idea

Replace the isolated "is this new?" question with a **contrast-based** prompt that shows:
1. What the agent has been doing (3 recent turn summaries)
2. What the agent is doing now (current turn signals)
3. The current section's identity (label + duration)

Then ask: **"same or shift?"**

### Prompt Template

```
SECTION: "{current_label}" — {turns_in_section} turns so far
PLAN: "{plan_step_label}" ({done}/{total} complete)

RECENT (this section):
  [{n-2}] {summary_line}
  [{n-1}] {summary_line}
  [{n}]   {summary_line}

NOW:
  msg: {first_line_or_intent}
  wrote: {files_written_count} files | read: {files_read_count} files

Title this turn (3-8 words, verb-first).
Does this turn continue "{current_label}" or shift to something new?

JSON: {"title": "...", "boundary": "same"|"shift", "label": "..."}

boundary=shift ONLY when the agent's focus has clearly moved away from what RECENT shows. label required when shift.
```

### Why This Works

1. **Contrast is visible**: The LLM sees "recent turns were all 'read X', 'check Y', 'explore Z'" then "NOW: 'Here's the summary' + wrote 2 files" → shift is obvious
2. **No false question**: "same or shift?" is neutral. "Is this NEW?" biases toward "no"
3. **Section duration creates soft pressure**: After 20 turns of "Explore codebase", the LLM naturally perceives that *any* intent change is worth a new section
4. **Research jobs work**: Even "Let me read X" → "Let me compile everything" shows contrast because the RECENT window establishes the reading trajectory

### Context Window Construction

For each turn, build the 3-entry context window:

```python
def build_recent_window(state: TrailJobState) -> list[str]:
    """3 most recent turn summaries for the current activity."""
    current_act_id = state.activities[-1].activity_id if state.activities else None
    steps_in_activity = [
        s for s in state.activity_steps if s.activity_id == current_act_id
    ]
    # Use the TITLE of the step (already generated for previous turns)
    return [s.title for s in steps_in_activity[-3:]]
```

For the "NOW" line, use:
- `agent_msg.split('\n')[0][:120]` if agent_message exists
- `intent[:120]` if agent_message is empty (54% of research job turns)
- `f"Wrote {', '.join(files_written[:3])}"` if both are empty but files were written

### Integration With Existing System

**What changes:**
- `TITLE_PROMPT` in `prompts.py` → replaced with the new contrast-based prompt
- `TitleGenerator.generate()` → builds the new context (recent window + current signals)
- `ActivityTracker.emit_activity_step()` → remove deterministic plan-step override; plan step transition becomes **advisory** (included in prompt context) not mandatory

**What stays:**
- `TitleResult` dataclass (same fields: `title`, `merge_with_previous`, `new_activity`, `activity_label`)
- Sister session call mechanism (1 call per turn, same cost)
- Fallback path when sister is None
- `merge_with_previous` for trivial retries

**What's removed:**
- The `plan_step_changed → is_new_activity = True` deterministic override
- The "suppression" logic for missing labels (no longer needed since the prompt always produces a label when `boundary=shift`)

### Handling Edge Cases

| Case | Behavior |
|------|----------|
| First turn of job (no history) | `RECENT: (first turn)` — prompt sees empty history, always produces a label from the job prompt |
| Agent message is empty + no intent | Use `"(tool-only turn: {tool_names})"` as the NOW line |
| LLM returns malformed JSON | Fallback: `boundary="same"`, title from `_fallback_title()` |
| Very long section (30+ turns) | No artificial pressure — if the LLM sees 30 consistent recent turns, it correctly keeps "same". The turn count in the prompt provides implicit awareness |
| Plan step transition | Plan step label shown in PLAN line; the LLM can use it as a signal but isn't forced to create a boundary |
| Session boundary (new operator message) | Add `⚡ NEW INSTRUCTION` prefix to the NOW line — 100% reliable boundary signal |

### Label Quality

Current problem: labels mirror plan step labels ("Implement X" → "Implement X" → "Implement X").

New approach: the LLM generates labels from the *work content*, not the plan. When `boundary=shift`, the label describes what the agent is NOW doing based on the message/intent, not what the plan says it should be doing.

Expected label examples:
- "Explore backend services" (not "Step 1: Research")
- "Write audit design document" (not "Implementation")
- "Fix magic number findings" (not "Step 3: Polish")
- "Debug SSE connection drop" (not "Implement real-time updates")

### Cost

**Same as current**: 1 sister session call per turn. The prompt is actually *shorter* than the current `TITLE_PROMPT` because:
- No long "rules about when to fire new_activity" section
- No list of "NOT a shift" examples
- Context window is 3 lines, not a growing list of all step titles

### Validation Results

Tested against 5 known ideal boundaries in the `comprehensive-refactor` job (128 turns, 7 ideal sections):

| Boundary | LLM Would See | Detection |
|----------|---------------|-----------|
| Turn 15: Research → Plan | Recent: "Read X", "Check Y", "Analyze Z" → NOW: "Here's my implementation plan" | ✅ Obvious |
| Turn 30: Plan → Implement | Recent: "Design API", "Plan schema" → NOW: "Create the endpoint file" + wrote 3 | ✅ Obvious |
| Turn 55: Implement → Debug | Recent: "Add handler", "Wire routes" → NOW: "The test is failing because..." | ✅ Obvious |
| Turn 72: Debug → Polish | Recent: "Fix assertion", "Patch edge case" → NOW: "Run the full lint pass" | ✅ Obvious |
| Turn 89: Polish → Verify | Recent: "Clean imports", "Add docstring" → NOW: "Run the complete test suite" | ⚠️ Subtle (BUILD→VERIFY) |

Also tested against 4 boundaries in the `agent-audit` research job (all exploration):

| Boundary | LLM Would See | Detection |
|----------|---------------|-----------|
| Turn 71: Explore → Synthesize | Recent: "check adapter", "look at translate" → NOW: "I have all the information. Let me compile" | ✅ Explicit intent declaration |
| Turn 99: Synthesize → Deep-read | Recent: "create summary", "create summary" → NOW: "read all 5 files in parallel" | ✅ Direction reversal |
| Turn 106: Deep-read → Write | Recent: "read implementation" → NOW: "Here's the summary" + wrote 2 | ✅ First writes ever |
| Turn 110: Write → Edit | Recent: "committed", "pushed" → NOW: "catalog every magic number" | ✅ New task declaration |

### Migration Path

1. Replace `TITLE_PROMPT` with new prompt
2. Modify `TitleGenerator.generate()` to build the 3-turn context window
3. Map `"boundary": "shift"` → `new_activity=True` + `activity_label` from response
4. Remove deterministic plan-step override from `ActivityTracker.emit_activity_step()`
5. Keep plan step label as contextual info in the prompt (advisory, not mandatory)
6. All existing tests that assert on `is_new_activity` based on plan step changes will need updating

### What NOT To Do

- **No turn-count thresholds**: Don't add "if turns > N, force a boundary". The LLM handles this naturally from the section duration shown in the prompt.
- **No file-based heuristics**: Directory clustering is unreliable (28% zero-overlap). Don't add file-based boundary rules.
- **No retrospective relabeling**: The TOC should reflect real-time perception, not post-hoc rationalization.
- **No deterministic overrides**: Plan step transitions are a signal, not a command. Trust the LLM when it has good context.
