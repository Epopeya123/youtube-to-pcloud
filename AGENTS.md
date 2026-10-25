# AGENTS.md

This project's own rules are in [CLAUDE.md](CLAUDE.md). Claude Code loads it automatically; any other agent (Codex, Antigravity) must read it in full before working here.

<!-- BEGIN agents-scratch global rules pointer (source: Epopeya123/agents-scratch instructions/repo-pointer.md; change it there, then in every repo listed in its AGENT-INDEX.md) -->
## The owner's global rules (every agent, including cloud sessions)

The owner (Nacho) keeps one set of rules for every agent (Claude Code, Codex, Antigravity), and his shared skills, in
the private repository `Epopeya123/agents-scratch`: `instructions/global.md` and `skills/`, listed in `AGENT-INDEX.md`.
On his laptop they are loaded automatically. In a cloud session they are not: read `instructions/global.md` there if
you can reach it (for example
`gh api repos/Epopeya123/agents-scratch/contents/instructions/global.md -H "Accept: application/vnd.github.raw"`).
If you can't, follow at least these:

1. Lead with the answer and be brief; gloss a technical term in one plain line. He is a domain expert, not a software
   engineer.
2. Decide technical trade-offs and do the work yourself; ask him only real business decisions, in one clear line.
3. Every change on its own feature branch (`fix/`, `feat/`, `cleanup/`, `chore/`), in its own git worktree where you
   can; never commit straight to `main`/`master`; push every commit; land it with a `--no-ff` merge, then delete the
   merged branch.
4. Never delete a branch with unmerged pushed commits, or otherwise discard pushed work, unless he says so.
5. To change these rules or a shared skill, edit them in `agents-scratch` (on a branch), not in this repository.
<!-- END agents-scratch global rules pointer -->
