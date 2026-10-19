# Synthetic school emails

Fake emails we wrote ourselves, for evals and tests. No real school, no real inbox. Evals read these
files; they never call the Gmail API.

Each file: `sender`, `subject`, `body`, `label` (`task` | `closure` | `no_task` | `injection`) and `expected` —
what a correct extraction produces, empty when there is nothing. A task carries `kind: task` with
`title`, `child`, `due`, `category` and `prep_days`; a closure carries `kind: closure` with `title`
and `date`.
