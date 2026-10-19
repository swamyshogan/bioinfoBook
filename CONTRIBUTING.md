# Contributing to bioinfoBook

bioinfoBook is only as good as its cheat sheets, and those come from people who use these tools every day. There are three ways to help, from easiest to most involved.

## 1. A command is missing → open an issue

If a tool is already in bioinfoBook but a command you use isn't, open an **Add a missing command** issue. You can do it from the terminal:

```bash
bioinfobook suggest samtools        # opens the issue form for that tool
bioinfobook share my-hpc-3          # turns one of your private cheats into a suggestion
```

You can also go to the repo's **Issues → New issue → Add a missing command**. Give it the tool, a short description, the command, and any notes. A maintainer or another contributor turns it into a JSON line.

## 2. A whole tool is missing → request it

Open a **Request a new tool** issue (or run `bioinfobook suggest bedtools`) with the commands you'd want in it. Even a rough list helps.

## 3. Write the JSON yourself → open a pull request

1. Fork the repo and clone it.
2. Edit `db/<tool>.json`, or create it for a new tool (template below).
3. Run the checker:
   ```bash
   python3 bioinfobook.py validate
   ```
4. Try your cheats in the picker: `python3 bioinfobook.py "#<tool>"`.
5. Open a pull request. GitHub runs the same checker on it automatically.

### File format

One file per tool. The file name must match the `"tool"` field.

```json
{
  "tool": "bedtools",
  "description": "Genome arithmetic — intersect, merge, coverage and more on BED / BAM / VCF intervals",
  "homepage": "https://bedtools.readthedocs.io",
  "contributors": ["your-github-username"],
  "cheats": [
    {"title": "Regions that overlap another BED", "cmd": "bedtools intersect -a {{a.bed}} -b {{b.bed}} -u", "notes": "-v instead of -u keeps regions with no overlap"},
    {"title": "Merge overlapping intervals", "cmd": "bedtools merge -i {{sorted.bed}}"}
  ]
}
```

| field | required | what it is |
|---|---|---|
| `tool` | yes | lowercase name, same as the file name (`bedtools` → `bedtools.json`) |
| `description` | yes | one line saying what the cheats cover. It's shown in the picker and the README |
| `homepage` | no | link to the tool's docs |
| `contributors` | no | GitHub usernames, so we can credit you |
| `cheats` | yes | the list of cheats |
| `cheats[].title` | yes | what the command does, under 80 characters. **This is what people search for**, so use the words they'd type |
| `cheats[].cmd` | yes | the command. Use `\n` for multi-line commands |
| `cheats[].notes` | no | gotchas, what the flags mean, macOS vs Linux differences |

### Blanks

Write `{{name}}` for anything the user has to fill in, or `{{name:default}}` to suggest a default. When someone copies the cheat, bioinfoBook asks for each blank. The same blank used twice is asked for only once.

```
samtools sort -@ {{threads:4}} -o {{sorted.bam}} {{in.bam}}
```

### House rules

- **Test every command** you add, on real data if you can.
- **Add new cheats at the end** of the `cheats` list. Ids like `samtools-12` come from each cheat's position, so inserting in the middle renumbers everyone's ids.
- **Nothing private:** no usernames, hostnames, cluster names, lab paths, tokens or passwords. Use blanks instead (`{{user}}@{{login_host}}`).
- **One cheat per line** in the JSON, like the existing files. It keeps reviews and diffs readable.
- **Prefer portable commands.** If something differs between macOS and Linux (`sed -i`, `zcat`, `md5`), say so in `notes`.
- **Bioinformatics first.** General tools (git, tmux, shell) are welcome when the cheats are the ones people doing analysis actually need.

Thank you! ✦
