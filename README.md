# Tour Guide

Guided tours of a codebase that adapt to what you already know.

Tour Guide has Claude read a repository and write a step-by-step tour of it. Each step comes with an explanation, the exact lines of code it's about (highlighted), and links to the docs worth reading. As you go, you tell the tour what you know ("I don't need basic CRUD explained, but go deep on the AI frameworks"), and it changes how much detail you get. Your "Too basic" and "Too much" answers and the quick checks you pass or miss adjust it too.

It's built for going back through a project you shipped without fully understanding it, and coming out the other side owning the code.

**Demo:** a tour of [calebbratton/pitwall](https://github.com/calebbratton/pitwall) is in [`examples/pitwall`](examples/pitwall). Open `pitwall-tour.html` in a browser.

## How it works

1. **Generate (once per repo).** A Claude agent explores the repo with read-only tools. It groups what it finds into topics, then writes 10–18 steps from the entry point to the core logic to the supporting pieces. Every step is written at three depths:
   - **brief**: what's specific to this repo, for someone fluent in this kind of code.
   - **standard**: a clear explanation for a developer new to the repo.
   - **deep**: why the code exists, what it guards against, and what breaks if you change it.

   Each step also gets highlight ranges, doc links and a quick check. Every file path and line range is checked against the real files, and the agent has to fix any that don't match.
2. **Take the tour (free).** The viewer switches between the prepared depths per topic, based on what you tell it and how you answer. Moving through steps, giving feedback and changing depths use no AI at all.
3. **Ask for more (only when you want it).** "Go deeper still" and "Ask about this code" (including about lines you select) send just that step's code to a model.

The tour map shows how much of the repo the tour covers and how much you've walked through. For anything not covered yet, generate a focused follow-up tour with `--scope src/some/folder`.

## Using it

### In VS Code or Cursor

The extension in [`extension/`](extension) plays tours inside your editor. The explanation sits in a side panel, and the real file opens next to it with the lines highlighted. Tours live in `.tours/*.json` in your repo, so commit them and teammates can take them too, without any AI.

- **Tour Guide: Generate a Tour of This Workspace…** writes a new tour with Claude Code.
- **Tour Guide: Open Tour…** starts a saved tour.
- `Ctrl+Alt+]` / `Ctrl+Alt+[` move to the next or previous step. Select lines and run **Ask the Tour About Selected Lines** to ask about them.

Build it with `cd extension && npm install && npm run package`, then install the `.vsix` with **Extensions: Install from VSIX…**.

### From the command line

```bash
pip install -e .
tourguide generate path/or/git-url -o tour.json                   # explore with Claude and write the tour
tourguide generate . --scope src/sim -o sim-tour.json             # a focused follow-up tour
tourguide serve tour.json --repo . --editor cursor                # browse it locally with live answers
tourguide render tour.json -o tour.html                           # a single HTML file you can share
```

## Cost

Nothing needs an API key.

- **Generating** runs through Claude Code (`claude -p`), so it counts against your Claude plan. A 16-step tour of pitwall took 30 agent turns, roughly one solid Claude Code task. Use `--model sonnet` and `--steps` to make it lighter. `--engine api` is there if you'd rather use an `ANTHROPIC_API_KEY`.
- **Live answers** in the extension and in `tourguide serve` also use `claude -p`, with a fast model for reading your notes. A tour published as a claude.ai artifact uses the reader's own Claude account.
- **Without any AI**, prepared tours still play fully, and your notes are matched to topics by keyword.

The extension can also answer live questions with a chat model your editor provides (for example GitHub Copilot) through `tourguide.backend`. Generating tours with models other than Claude is planned.

## Tour format

A tour is one JSON file: `title`, `summary`, `topics` (id, label, description, keywords) and `steps`. Each step has a `topic`, a `file`, `highlights` (start, end, label), an `explanation` with `brief`/`standard`/`deep` markdown, `links` and an optional `check`. Explanations can link to other code inline as `[name](path/to/file.py#L10-L20)`. The JSON Schema lives in [`tourguide/schema.py`](tourguide/schema.py).

## Layout

| Path | What it is |
|---|---|
| `tourguide/` | Python package: the generator agents, the validator, the CLI and the local server |
| `tourguide/viewer/template.html` | The viewer, shared by the browser, `serve`, the artifact and the extension |
| `extension/` | The VS Code / Cursor extension (TypeScript) |
| `examples/pitwall/` | A generated tour of pitwall |
| `tests/`, `extension/test/` | Python and Node tests |
