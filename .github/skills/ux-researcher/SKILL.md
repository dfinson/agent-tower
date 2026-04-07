---
name: ux-researcher
description: "UX research and design toolkit — generate user personas, create journey maps, plan usability tests, and synthesize research findings into actionable design recommendations for CodePlane's UI."
---

# UX Researcher & Designer

Generate user personas from research data, create journey maps, plan usability tests, and synthesize research findings into actionable design recommendations.

## Context

CodePlane is a control plane for supervising coding agents. Users are developers who:
- Kick off coding agent jobs with task descriptions
- Monitor agent progress in real-time (plan steps, tool calls, file changes)
- Review and approve agent actions
- Inspect diffs and terminal output
- Analyze cost and performance metrics

## Workflows

### Workflow 1: Generate User Persona

**When**: You need to understand who uses CodePlane and how.

**Steps:**

1. **Identify user segments** from the codebase:
   - Read the app's features to understand what users can do
   - Identify different usage patterns (power user vs occasional, solo vs team)
   - Look at the settings/config to understand customization points

2. **Generate personas** covering:

   | Component | What to Include |
   |-----------|----------------|
   | Archetype | Power user, casual user, team lead, etc. |
   | Demographics | Role, tech proficiency, team size |
   | Goals | What they're trying to achieve with CodePlane |
   | Frustrations | Pain points from the current UI |
   | Design implications | Actionable recommendations |

3. **Persona archetypes for CodePlane:**

   | Archetype | Context | Design Focus |
   |-----------|---------|--------------|
   | Solo Developer | Uses agents for personal projects, cost-conscious | Efficiency, clear cost visibility |
   | Tech Lead | Supervises multiple agents, reviews team output | Multi-job overview, approval workflows |
   | New User | First time using agent supervision | Onboarding, clarity, low cognitive load |
   | Power User | Daily use, multiple concurrent jobs | Keyboard shortcuts, dense info display |

### Workflow 2: Create Journey Map

**When**: You need to visualize the end-to-end user experience.

**Steps:**

1. **Define scope:**
   | Element | Description |
   |---------|-------------|
   | Persona | Which user type |
   | Goal | What they're trying to achieve |
   | Start | Trigger that begins journey |
   | End | Success criteria |

2. **Map the stages:**
   ```
   Create Job → Monitor Progress → Review Changes → Approve/Reject → Complete
   ```

3. **Fill in layers for each stage:**
   ```
   Stage: [Name]
   ├── Actions: What does user do?
   ├── Touchpoints: Where do they interact?
   ├── Emotions: How do they feel? (1-5)
   ├── Pain Points: What frustrates them?
   └── Opportunities: Where can we improve?
   ```

4. **Identify opportunities:**
   Priority Score = Frequency × Severity × Solvability

### Workflow 3: Plan Usability Test

**When**: You need to validate a design decision.

**Steps:**

1. **Define testable questions:**

   | Vague | Testable |
   |-------|----------|
   | "Is the transcript readable?" | "Can users find what tool the agent used 3 steps ago in <10s?" |
   | "Are steps clear?" | "Can users explain what the agent is doing from the step list?" |
   | "Is the diff useful?" | "Can users identify which files changed in a step in <5s?" |

2. **Design tasks:**
   ```
   SCENARIO: "You kicked off an agent to add a login page. It's been running for 5 minutes."
   GOAL: "Find out what file the agent is currently editing."
   SUCCESS: "User identifies the correct file name."
   ```

3. **Define success metrics:**
   | Metric | Target |
   |--------|--------|
   | Completion rate | >80% |
   | Time on task | <2× expected |
   | Error rate | <15% |
   | Satisfaction | >4/5 |

### Workflow 4: Synthesize Research

**When**: You have observations/findings and need actionable insights.

**Steps:**

1. **Code the data** — tag each observation:
   - `[GOAL]` - What they want to achieve
   - `[PAIN]` - What frustrates them
   - `[BEHAVIOR]` - What they actually do
   - `[CONTEXT]` - When/where they use the feature
   - `[QUOTE]` - Direct user words (or inferred from code review)

2. **Cluster patterns** into themes

3. **Extract key findings** per theme:
   - Finding statement
   - Supporting evidence
   - Frequency
   - Business impact
   - Recommendation

4. **Prioritize opportunities:**
   | Factor | Score 1-5 |
   |--------|-----------|
   | Frequency | How often does this occur? |
   | Severity | How much does it hurt? |
   | Breadth | How many users affected? |
   | Solvability | Can we fix this? |

## Usability Issue Severity

| Severity | Definition | Action |
|----------|------------|--------|
| 4 - Critical | Prevents task completion | Fix immediately |
| 3 - Major | Significant difficulty | Fix before release |
| 2 - Minor | Causes hesitation | Fix when possible |
| 1 - Cosmetic | Noticed but not problematic | Low priority |

## Validation Checklist

### Persona Quality
- [ ] Based on actual app feature analysis
- [ ] Specific, actionable goals
- [ ] Frustrations derived from real UI patterns
- [ ] Design implications are specific

### Journey Map Quality
- [ ] Scope clearly defined
- [ ] Based on real user flows from the code
- [ ] Pain points identified per stage
- [ ] Opportunities prioritized

### Research Synthesis Quality
- [ ] Patterns based on 3+ data points
- [ ] Findings include evidence
- [ ] Recommendations are actionable
- [ ] Priorities justified
