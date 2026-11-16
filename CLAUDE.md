# trader-skill

- The stock bot is in `stockbot/` and is developed on the `stockbot` branch. The phone pulls
  `origin stockbot`.
- Graphify indexes `main`. After pushing `stockbot`, also run `git push origin stockbot:main`
  (a fast-forward: `main` has nothing of its own).
- Tests: `python3 stockbot/tests/run.py`.
- Rafael's Obsidian vault (bot notes only, nothing personal) is the `claude-vault` branch of the
  private `77689/memebot-data` repo. The phone syncs it both ways every 5 minutes
  (`stockbot/vault_sync.sh`, called by sync.sh), so edit it with normal commits on top and never
  force-push. If the phone hits a conflict it pushes its side to `claude-vault-phone`: merge that
  into `claude-vault`.
- No keys in the repo: Alpaca keys live in `~/.stockbot_env` and the Tiingo key in `~/.tiingo_key`,
  both on the phone only. The bot trades paper only; going live is a deliberate code change.
