_2026-11-11, patch 3.29.3c, 2925 wiki pages, 26962 chunks, query rewriting, answers by deepseek/deepseek-flash._

| Metric | Score |
|---|---|
| Expected page in top 8 | 100% |
| Expected pages found (recall@8) | 98% |
| Mean reciprocal rank | 0.90 |
| Cases passed | 96% |
| Required facts mentioned | 98% |
| Answers with only valid citations | 100% |
| Groundedness (judge, 1-5) | 4.48 |
| Relevance (judge, 1-5) | 4.96 |
| Says so when the wiki doesn't cover it | 100% |

| Category | Cases | Hit@8 | Passed |
|---|---|---|---|
| mechanic | 18 | 100% | 94% |
| gem | 10 | 100% | 100% |
| unique | 5 | 100% | 100% |
| ascendancy | 5 | 100% | 100% |
| indirect | 8 | 100% | 100% |
| unanswerable | 5 | n/a | 100% |
| build | 2 | 100% | 50% |

<details><summary>2 failing cases</summary>

- `leech-recovery`: missing: damage dealt / damage you deal / damage done / damage the enemy takes / damage taken / based on damage / of the damage / of damage
- `build-create-rf`: judge: grounded 2, relevant 3 (The answer cites wiki mechanics correctly but fabricates most build specifics (gems, ascendancy, gear, passives, DPS) that the Path of Building results do not show, and the export is a near-empty skeleton.)

</details>
