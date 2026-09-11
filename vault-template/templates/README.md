# Templates

Note schemas the tool server reads and writes. These are contracts, not
suggestions — `derive` writes `derive.md`'s shape and `record_grade` expects to
find it.

| Template | Written by | Read by |
|---|---|---|
| `derive.md` | `derive` | `submit_artifact`, `record_grade` |
| curriculum topic | `smrt-curriculum seed` | `smrt-curriculum audit`, the `teach` skill |

The curriculum-topic shape lives in `vault_tools/curriculum.py` rather than
here, because it is emitted by code rather than filled in by hand. Its contract
is narrower than it looks: seeding writes the canon fields **once** and never
returns, so `relevance`, `relevance_note`, `first_taught` and `outcomes` are
yours alone. A canon that has moved is reported by `audit`, not repaired.

## Why front matter

It is what makes the record queryable. With `type`, `concept`, `status` and
`score` as fields, Dataview answers "every derivation I got wrong" or
"everything touching [[Fisher information]]" — the difference between a pile of
sessions and a learning record.

## Why the rubric is a hash first

`rubric_sha256` is written before you see the task; the plaintext `rubric`
appears only after grading. Writing the expected steps into a note you are
about to open would spoil the exercise, and writing them only afterwards would
make the pre-commitment unverifiable.

With the hash you can check afterwards that the bar was not moved once your
answer was seen. The default failure of LLM grading is sycophancy, so a bar
that is verifiably fixed in advance is doing real work.
