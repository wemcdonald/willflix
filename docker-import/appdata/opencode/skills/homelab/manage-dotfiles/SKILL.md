---
name: manage-dotfiles
description: Use when adding shell aliases, functions, zsh plugins, asdf tool versions, key bindings, or modifying any shell configuration in the dotfiles repo
---

# Dotfiles Management

Repository: `~/dotfiles`
Shell: zsh with Oh My Zsh

## File Mapping

| Change type | File |
|-------------|------|
| General aliases | `~/.zsh/personal/aliases.zsh` |
| Utility functions | `~/.zsh/personal/funcs.zsh` |
| Git aliases/functions | `~/.zsh/personal/git.zsh` |
| Key bindings | `~/.zsh/personal/keys.zsh` |
| Server-specific (lafayette) | `~/.zsh/personal/hostname/lafayette/*.zsh` |
| Oh My Zsh plugins | `~/.zsh/oh-my-zsh-init.zsh` |
| Global tool versions | `~/.tool-versions` |

## Checklist

- [ ] Identify correct file from the mapping table above
- [ ] Read the target file to match existing style
- [ ] Make changes
- [ ] Verify no duplication with existing aliases/functions (see key aliases below)
- [ ] Test: `source ~/.zshrc` or open new shell

## Key Existing Aliases (Do Not Duplicate)

**Lafayette server-specific:**
- `dc` = docker compose with server compose file
- `sp` = sudo -u plex

**Git (in git.zsh):**
- `g` = git
- `gs` / `ga` / `gc` / `gco` / `gd` / `gl` / `push` / `pull` / `sync`

**Shell:**
- `resource` = re-source zshrc

## asdf Tool Management

Current plugins: `golang`, `nodejs`, `yarn`, `python`, `uv`

### Add or update a tool

```bash
# Add new plugin (skip if already installed)
asdf plugin add {tool}

# Install a version
asdf install {tool} {version}

# Set as global default (updates ~/.tool-versions)
asdf global {tool} {version}

# Verify
asdf current {tool}
```

### Check what's installed

```bash
asdf current          # All tools and active versions
asdf list {tool}      # Installed versions of a specific tool
asdf list all {tool}  # All available versions
```

## Conventions

- **Auto-symlink**: The dotfiles repo auto-symlinks to `~/` on shell init. No manual symlinks needed.
- **Propagation**: Changes in `~/dotfiles/` propagate automatically.
- **Host-specific config**: Goes in `hostname/{hostname}/` dirs, sourced conditionally. Use this for anything that only applies to one machine.
- **Style**: Match existing code style in each file. Read before writing.
- **Testing**: Always `source ~/.zshrc` after changes to verify no syntax errors.

## Adding an Oh My Zsh Plugin

1. Read `~/.zsh/oh-my-zsh-init.zsh`
2. Add plugin name to the `plugins=(...)` array
3. If it's a custom plugin, clone it to `~/.oh-my-zsh/custom/plugins/`
4. `source ~/.zshrc` to activate
