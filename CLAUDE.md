# trader-skill

- The stock bot is in `stockbot/` and is developed on the `stockbot` branch. The phone pulls
  `origin stockbot`.
- Graphify indexes `main`. After pushing `stockbot`, also run `git push origin stockbot:main`
  (a fast-forward: `main` has nothing of its own).
- Tests: `python3 stockbot/tests/run.py`.
- Rafael's rule: use Graphify for every code lookup and every code change. Find code with
  graphify_find / query_graph / graphify_node instead of reading whole files, and before changing a
  function check graphify_callers / graphify_impact / graphify_tests_for. Grep only for literal
  strings and files Graphify doesn't index. Push `stockbot:main` afterwards so the index catches up.
- Rafael's Obsidian vault (bot notes only, nothing personal) is the `claude-vault` branch of the
  private `77689/memebot-data` repo. The phone syncs it both ways every 5 minutes
  (`stockbot/vault_sync.sh`, called by sync.sh), so edit it with normal commits on top and never
  force-push. If the phone hits a conflict it pushes its side to `claude-vault-phone`: merge that
  into `claude-vault`.
- Rafael's standing rules: anything new about the bots (changes, results, decisions, commands,
  to-dos) also goes into the vault in the same session, in the matching note or a new one linked
  from Home.md. And read the vault for context whenever a bot task needs it.
- Start every bot task at the vault's `brain.md` (decisions, ideas, lessons); log new decisions in
  `decisions.md` and new ideas in `ideas.md`.
- Every bot task runs through the agent crew in the vault's `bots/agent-crew.md` (Boss, Scout,
  Planner, Builders, Checker, Fixer, Shipper, Watcher, Librarian); read `bots/lessons.md` before
  starting and add a line to it after.
- Research rules: every new backtest idea is logged in the vault's `bots/tries.md` and its result is
  deflated for the number of tries (`stockbot/backtest/deflated.py`); data from 2024-01-01 on is locked
  (`stockbot/backtest/holdout.py`) and used once per idea as a final exam. Unproven ideas that look good go
  to `bots/experiments.md` (small live paper parts with a review date) only with Rafael's yes.
- Always use ponytail: Builders make the smallest complete change (the ponytail skill) and the
  Checker reviews with ponytail-review.
- No keys in the repo: Alpaca keys live in `~/.stockbot_env` and the Tiingo key in `~/.tiingo_key`,
  both on the phone only. The bot trades paper only; going live is a deliberate code change.
