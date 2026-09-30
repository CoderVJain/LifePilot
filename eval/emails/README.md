# Synthetic school emails

Fake emails we wrote ourselves, for evals and tests. No real school, no real inbox. Evals read these
files; they never call the Gmail API.

Each file: `sender`, `subject`, `body`, `label` (`task` | `no_task` | `injection`) and `expected` —
the tasks a correct extraction produces, empty when there are none.
