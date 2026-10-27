# Tour Guide for VS Code and Cursor

Guided tours of a codebase, played in your editor and adapted to what you already know.

- **A side panel explains each step** while the real file opens next to it, with the relevant lines highlighted and labelled.
- **Tell the tour about yourself** in plain words, for example "skip the CRUD, go deep on the agent". You can also use the Too basic / Just right / Too much buttons and quick checks. The tour changes its depth per topic as you go.
- **Select lines and ask about them.** "Go deeper still" writes a deeper explanation on the spot.
- **Tours are files** in `.tours/`. Commit them, and anyone on the team can take the tour without AI.

## Requirements

- Prepared tours need nothing.
- Generating tours and getting live answers need the [Claude Code](https://docs.claude.com/en/docs/claude-code/setup) CLI (`claude`), installed and signed in. Usage counts against your Claude plan, and no API key is needed.
- For live answers only, you can instead use a chat model your editor provides to extensions (setting `tourguide.backend`: `vscode-lm`).

## Commands

| Command | Default key |
|---|---|
| Tour Guide: Open Tour… | |
| Tour Guide: Generate a Tour of This Workspace… | |
| Tour Guide: Next Step | `Ctrl+Alt+]` (`Cmd+Alt+]` on macOS) |
| Tour Guide: Previous Step | `Ctrl+Alt+[` (`Cmd+Alt+[` on macOS) |
| Tour Guide: Ask the Tour About Selected Lines | editor context menu |

## Settings

| Setting | Default | |
|---|---|---|
| `tourguide.backend` | `auto` | `claude-code`, `vscode-lm` or `none` |
| `tourguide.claudePath` | `claude` | Path to the Claude Code CLI |
| `tourguide.model` | (Claude Code default) | Model for generating tours, e.g. `sonnet` |
| `tourguide.steps` | `16` | Target number of steps |
