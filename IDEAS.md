# Ideas & Future Work

## Cross-Channel Category Merging

Problem: Each channel gets its own categories with slightly different names. Need to unify them.

**Option A: Post-hoc merge**
- Collect all category names across channels (just names, not videos)
- LLM call: "Merge similar ones into a unified taxonomy of N categories"
- Output a mapping (e.g., "Resume and Application Optimization" → "Resume & Applications")
- Script renames/merges category folders

**Option B: Unified discovery upfront**
- Discover categories from ALL channels' titles at once
- Each channel's assignment step uses the shared taxonomy
- Downside: adding a new channel means re-running discovery (though it's cheap)

## Optimal Number of Categories

Problem: '5' is hardcoded in discover_categories.txt. How to pick the right number?

**Option A: Manual iteration**
- Run the pipeline with different N values, eyeball results, keep the best
- Cheap enough to be viable

**Option B: Let the LLM decide**
- "Identify the natural themes — use as many or as few as the content warrants"
- Loses the control knob but categories emerge from the data

**Option C: Bounded range**
- "Identify between 4 and 8 themes" — flexibility with guardrails

**Option D: Two-shot with cohesion rating**
- Ask LLM to propose categories AND rate cohesion of each (1-5)
- Low-scoring categories indicate forced groupings
- Still one cheap titles-only call
