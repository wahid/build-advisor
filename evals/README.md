# Evaluations

- `questions.yaml`: the evaluation set (see the comment at the top for the fields).
- `corpus.jsonl.gz`: a fixed slice of the wiki used in CI, so evaluations don't
  need the full multi-hour import. Regenerate it after changing the questions:
  `python manage.py export_eval_corpus` (needs a full database).
- `results/latest.json` / `latest.md`: the most recent run.

Run locally against your full database:

```bash
python manage.py run_evals                 # retrieval only, no LLM calls
python manage.py run_evals --answers       # also answers and an LLM judge
python manage.py run_evals --answers --update-readme
```

## Licence of the corpus

`corpus.jsonl.gz` contains text from the [Path of Exile Wiki](https://www.poewiki.net)
(poewiki.net), licensed under
[CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/). Each row
keeps the URL of its page. It's used here, non-commercially, to test retrieval.
