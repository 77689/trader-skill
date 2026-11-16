# trader-skill

- The stock bot is in `stockbot/` and is developed on the `stockbot` branch. The phone pulls
  `origin stockbot`.
- Graphify indexes `main`. After pushing `stockbot`, also run `git push origin stockbot:main`
  (a fast-forward: `main` has nothing of its own).
- Tests: `python3 stockbot/tests/run.py`.
- No keys in the repo: Alpaca keys live in `~/.stockbot_env` and the Tiingo key in `~/.tiingo_key`,
  both on the phone only. The bot trades paper only; going live is a deliberate code change.
