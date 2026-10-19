# bioterminal ✦

**Bioinformatics cheat sheets in your terminal: animated, colourful, and written by the community.**

Stop digging through old notebooks and Stack Overflow tabs for that one `awk` line that prints every 4th line of a FASTQ. Type a few letters, press Enter, and the command is on your clipboard, with the blanks filled in.

<sub>Ideation by **Shogan** · Executed by **Claude**</sub>

```
   █▄▄ █ █▀█ ▀█▀ █▀▀ █▀█ █▀▄▀█ █ █▄ █ ▄▀█ █     bioinformatics cheat sheets in your terminal
   █▄█ █ █▄█  █  ██▄ █▀▄ █ ▀ █ █ █ ▀█ █▀█ █▄▄   ✦ 296 cheats · 5 tools

  ╭──────────────────────────────────────────────────────────────────────────────────────────╮
  │ ❯ fastq seq▌                                                                       5/296 │
  ╰──────────────────────────────────────────────────────────────────────────────────────────╯
  ╭─ 5 matches ──────────────────────────────────────╮ ╭─ preview ───────────────────────────╮
  │▌  terminal  Print only the sequences…  gzip -cd… │ │ Print only the sequences (every 4th │
  │   terminal  Count reads containing a…  gzip -cd… │ │ line from line 2)                   │
  │   terminal  Count a sequence on both…  s={{seq…  │ │                                     │
  │   terminal  Pull out whole reads con…  gzip -cd… │ │ ▎ gzip -cd {{reads.fastq.gz}} |     │
  │   terminal  Quick stats for FASTA/FA…  seqkit s… │ │ ▎   awk 'NR % 4 == 2'               │
  ╰──────────────────────────────────────────────────╯ ╰─────────────────────────────────────╯
    ⏎  copy   ^T  type   ^A  add   ^E  edit   ^D  delete   esc  quit
```

## Features

- **Search as you type.** Fuzzy matching on titles, commands and notes. `#samtools` limits the search to one tool.
- **Copy or type it in.** Enter copies to your clipboard and tmux buffer. `Ctrl+T` types the command into your prompt so you can edit it before running.
- **Fill in the blanks.** Cheats like `samtools sort -@ {{threads:4}} -o {{out.bam}}` ask for each value before copying.
- **Your own private cheats.** Save the commands you use often (your cluster login, your lab's pipeline) with a description to search by. They stay on your computer and are never part of the repo.
- **Made for tmux.** One line in your config gives you a `prefix + C` popup over whatever you're working on.
- **Nice to look at.** Catppuccin colours, smooth animations, syntax-coloured commands. Turn the animation off with `--no-anim`.
- **Zero dependencies.** One Python 3.8+ file and the standard library. Runs on macOS and Linux.

## Install

```bash
git clone https://github.com/swamyshogan/bioterminal.git
cd bioterminal
./install.sh
```

This links `bioterminal` into `~/.local/bin` and prints the optional tmux lines. To uninstall, delete `~/.local/bin/bioterminal`.

## Usage

```bash
bioterminal                    # open the picker
bioterminal samtools sort      # open it already searching
bioterminal tools              # list every cheat sheet
bioterminal ls --tool chimerax # print a whole sheet
bioterminal cp terminal-47     # copy one by its id
```

| key | in the picker |
|---|---|
| `⏎` | copy to clipboard and tmux buffer |
| `Ctrl+T` | type it into your prompt (doesn't run it) |
| `↑ ↓` / `Ctrl+P Ctrl+N` / mouse | move |
| `Ctrl+A` · `Ctrl+E` · `Ctrl+D` | add · edit · delete |
| `esc` | clear the search, then quit |

### Private cheats

```bash
bioterminal add 'ssh me@login.my-cluster.edu' -d "Log in to the cluster" -c hpc
bioterminal add -l -c rnaseq          # save the last command you ran
bioterminal add                       # asks for command, description and category
```

Private cheats live in `~/.config/bioterminal/private/<category>.json` and show up in search next to the community ones, marked with `◆`. Search `#my` to see only yours. If one would help others, `bioterminal share <id>` opens a pre-filled suggestion. It reminds you to strip anything personal first.

## Available cheat sheets

| Tool | Cheats | What's covered | Homepage |
|---|---:|---|---|
| [chimerax](db/chimerax.json) | 66 | Molecular visualization — open structures, style, colour, select, measure, superimpose, maps, figures and movies | [link](https://www.cgl.ucsf.edu/chimerax/) |
| [git](db/git.json) | 58 | Version control for analysis code — everyday git, branches, undoing mistakes, and the GitHub CLI | [link](https://git-scm.com/) |
| [hpc](db/hpc.json) | 39 | Running jobs on a Slurm cluster — login, transfers, sbatch / srun, job templates, modules, conda, GPUs, Jupyter | [link](https://slurm.schedmd.com/) |
| [terminal](db/terminal.json) | 84 | Unix one-liners for bioinformatics — FASTQ / FASTA parsing, sequence search, awk / grep / sed, SAM, VCF, BED, GTF | — |
| [tmux](db/tmux.json) | 49 | Keep long analyses running after you disconnect — sessions, windows, panes, copy mode, config | [link](https://github.com/tmux/tmux/wiki) |

**296 cheats across 5 tools.** Regenerate this table with `bioterminal tools --markdown`.

## Contributing

bioterminal is community-driven: every cheat sheet is a plain JSON file in [`db/`](db/), one per tool.

- **A command is missing from a tool?** Open an [*Add a missing command*](../../issues/new?template=add-command.yml) issue, or run `bioterminal suggest <tool>`.
- **A tool is missing?** Open a [*Request a new tool*](../../issues/new?template=new-tool.yml) issue, or run `bioterminal suggest <tool>`.
- **Want to write it yourself?** Add or edit `db/<tool>.json`, run `python3 bioterminal.py validate`, and open a pull request.

The file format and house rules are in [CONTRIBUTING.md](CONTRIBUTING.md). Wanted next: samtools, bcftools, bedtools, seqkit, BLAST, minimap2 / bwa, STAR / salmon, GATK, Nextflow / Snakemake, conda / mamba, PyMOL, R / Bioconductor one-liners.

## Settings

| environment variable | default | what it does |
|---|---|---|
| `BIOTERMINAL_HOME` | `~/.config/bioterminal` | where private cheats and usage counts live |
| `BIOTERMINAL_DB` | `db/` next to the script | use a different cheat-sheet folder |
| `BIOTERMINAL_NO_ANIM` | unset | `1` turns animations off |
| `BIOTERMINAL_COLOR` | auto | `256` forces 256-colour mode, `truecolor` forces 24-bit |
| `BIOTERMINAL_REPO` | set in the script | the GitHub repo that `suggest` and `share` open issues on |

## License

[MIT](LICENSE). Use it, fork it, share it.

<sub>Ideation by **Shogan** · Executed by **Claude**</sub>
