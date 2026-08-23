# Contributing

Keep changes scoped to transforming a user's own authenticated Douyin favorites into local knowledge notes. Do not add bulk redistribution, credential collection, or long-term original-video archiving.

Before opening a pull request, run:

```bash
python scripts/audit_release.py --root .
python -m ruff check scripts tests
python -m unittest discover -s tests -v
```

For changes to discovery, state transitions, cleanup, OCR, or note validation, add a regression test that exercises the changed behavior without using a real account or cookies.
