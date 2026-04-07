---
name: ui-design-review
description: "Comprehensive UI/UX design review for CodePlane's web interface with accessibility analysis (WCAG), usability heuristics, and visual design critique. Use when asked to review UI, check accessibility, evaluate design quality, or critique interaction patterns."
---

# UI/UX Design Review

Systematic design review of CodePlane's web interface covering accessibility, visual design, usability, responsive behavior, and interaction patterns.

## Review Framework

### 1. Initial Analysis

Before reviewing, understand:
- **Target audience**: Developers supervising coding agents
- **Platform**: Web (React SPA), desktop-primary but must work on mobile
- **Design system**: Tailwind CSS, shadcn/ui components, dark/light mode
- **Key user goals**: Monitor agent progress, review changes, approve actions, debug issues

### 2. Comprehensive Review Areas

#### A. Accessibility (WCAG 2.1/2.2)

**Level A (Minimum):**
- [ ] All images have appropriate alt text
- [ ] Icons have accessible labels
- [ ] Content structure is logical without CSS
- [ ] Reading order is meaningful
- [ ] Semantic HTML used properly
- [ ] Color is not the only means of conveying information
- [ ] All functionality is keyboard accessible
- [ ] No keyboard traps
- [ ] Focus order is logical
- [ ] Focus is visible at all times

**Level AA (Target):**
- [ ] Text contrast ≥ 4.5:1 (3:1 for large text)
- [ ] Text resizable to 200% without loss
- [ ] Multiple ways to locate pages
- [ ] Headings and labels are descriptive
- [ ] Focus indicator is visible

**Provide Feedback On:**
- Specific WCAG violations with severity
- Missing ARIA labels and landmarks
- Color contrast issues with measured ratios
- Keyboard navigation problems
- Screen reader compatibility
- Focus management problems

#### B. Visual Design & Aesthetics

**Evaluate:**
- Visual hierarchy and layout structure
- Color palette and contrast
- Typography choices and hierarchy
- White space and density
- Visual balance and alignment
- Component visual consistency
- Dark mode / light mode parity

**Look For:**
- Cluttered or overwhelming layouts
- Poor visual hierarchy
- Inconsistent spacing
- Typography issues (too many sizes/families)
- Misaligned elements
- Dated design patterns

#### C. User Experience & Usability

**Nielsen's 10 Heuristics:**
1. Visibility of system status
2. Match between system and real world
3. User control and freedom
4. Consistency and standards
5. Error prevention
6. Recognition rather than recall
7. Flexibility and efficiency of use
8. Aesthetic and minimalist design
9. Help users recognize and recover from errors
10. Help and documentation

**Evaluate:**
- User flow logic and efficiency
- Navigation patterns and clarity
- Cognitive load
- Task completion efficiency
- Error prevention and recovery
- Feedback mechanisms
- Learnability for new users

#### D. Responsive Design & Layout

**Evaluate:**
- Breakpoint strategy (check Tailwind responsive prefixes)
- Mobile-first approach
- Touch target sizes (minimum 44x44px)
- Content reflow behavior
- Navigation adaptation
- Form layout on mobile

**Check breakpoints:**
| Width | What it represents |
|-------|-------------------|
| 1280px+ | Desktop (standard) |
| 1024px | Small desktop / tablet landscape |
| 768px | Tablet portrait |
| 375px | Mobile |

#### E. Typography & Readability

**Evaluate:**
- Font choices and pairings
- Type scale and hierarchy
- Line length (45-75 characters optimal)
- Line height (1.5-1.8 for body text)
- Font size (minimum 16px for body)

#### F. Color & Contrast

**Evaluate:**
- Color palette cohesion
- Contrast ratios (WCAG compliance)
- Color blindness accessibility
- Dark mode support quality
- Semantic color usage (success=green, error=red, etc.)

**Contrast Requirements:**
- Normal text: 4.5:1 (AA), 7:1 (AAA)
- Large text (18pt+): 3:1 (AA), 4.5:1 (AAA)
- UI components: 3:1 (AA)

#### G. Interactive Elements & Components

**Evaluate:**
- Button styles and states (default, hover, focus, active, disabled)
- Form controls and inputs
- Loading states and skeletons
- Error states and validation
- Tooltips and popovers
- Modals and dialogs
- Dropdown/select menus
- Accordions and collapsible content

**Component Checklist:**
- [ ] All states designed (default, hover, focus, active, disabled, error, success)
- [ ] Touch targets meet minimum size
- [ ] Interactive elements have clear affordances
- [ ] Focus indicators are visible
- [ ] Loading states prevent multiple submissions
- [ ] Error messages are helpful and specific

#### H. Navigation & Information Architecture

**Evaluate:**
- Primary/secondary navigation structure
- Breadcrumb implementation
- Navigation depth (≤3 levels)
- Current location highlighting
- Back button behavior

#### I. Forms & Data Entry

**Evaluate:**
- Form layout and structure
- Label placement and clarity
- Required field indicators
- Validation approach (inline vs on submit)
- Error messaging quality
- Data preservation on error

### 3. Review Output Format

Structure reviews as:

#### Executive Summary
- Overall assessment (1-3 paragraphs)
- Key strengths
- Critical issues requiring immediate attention
- Design maturity score

#### Findings by Area
For each area (A through I):
- **Strengths**: What works well
- **Issues**: Ranked HIGH/MEDIUM/LOW
- **Recommendations**: Specific, actionable fixes with code references

### 4. Priority Classification

**CRITICAL**: Prevents users from accessing core functionality, WCAG Level A violations
**HIGH**: Significantly impairs UX, WCAG Level AA violations, major usability issues
**MEDIUM**: Creates friction but has workarounds, visual inconsistencies
**LOW**: Polish, refinement, edge cases

## How to Review (Code-Based)

Since we review from source code:

1. **Read Tailwind classes** to evaluate colors, spacing, typography, responsive behavior
2. **Read component JSX** to evaluate semantic HTML, ARIA attributes, keyboard handling
3. **Read event handlers** to evaluate interaction patterns, feedback, error handling
4. **Read store selectors** to evaluate what data drives each view
5. **Check for accessibility** patterns: role attributes, aria-labels, tabIndex, onKeyDown handlers
6. **Check responsive** prefixes: sm:, md:, lg:, xl: in Tailwind classes

## Deliverables

1. Executive summary with overall assessment
2. Accessibility analysis with WCAG references
3. Visual design assessment
4. UX and usability findings
5. Responsive design evaluation
6. Prioritized list of issues (Critical → Low)
7. Specific, actionable recommendations with code snippets
