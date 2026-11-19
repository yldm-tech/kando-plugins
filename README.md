# Kando plugins

The community plugin directory of [Kando](https://github.com/yldm-tech/Kando): translation styles, study tasks, export templates, glossaries, word lists, dictionaries, AI service presets, site packs and reviewed script plugins that anyone can install from inside Kando.

Every pack here was reviewed in a pull request. On each merge, CI builds the packs, checks them with the same code Kando installs them with, signs the list of them (the index) with Kando's index key, and publishes it.

## Getting plugins

In Kando, open **Settings › Plugins › Browse Plugins…**. The Plugin Directory lists everything published here; search it, pick a kind, and install. Installing shows the same confirmation as a file you pick yourself, and a pack grants nothing by being listed: a task pack is off until you turn it on (it spends your AI tokens), a site pack asks for each domain, and a script plugin does nothing until you grant its permissions and turn it on.

The directory is served from:

- `https://kando.yldm.ai/plugin/index.json`, the signed index Kando reads (at most once a day on its own, or when you press Refresh)
- `https://kando.yldm.ai/plugin/packs/<file>`, the pack files it lists

Kando refuses an index that is not signed by its index key, is older than the one it already has, or lists a file whose size or SHA-256 does not match the download.

## What is here

| Folder | What |
|---|---|
| `packs/<kind>/<id>/` | Data packs: a `kando-plugin.json` and its data files, one folder per pack. CI zips each into `<id>-<version>.kandopack`. |
| `scripts/<id>/` | Script plugins: the signed `<id>-<version>.kandoplugin` and its source in `src/` for review. |
| `publishers.json` | Who may publish under which publisher id. |
| `tools/packs.py` | This repository's own checks and the pack builder (Python standard library only). |
| `worker/` | The Cloudflare Worker that serves the directory on kando.yldm.ai. |
| `.github/workflows/` | `validate.yml` and `preview-comment.yml` check pull requests and comment a preview; `publish.yml` signs and deploys on main. |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md): it is the plugin author guide, covering every kind, testing locally, publisher registration, the review, licensing, updates and removal.

To report a plugin that is broken, misleading or harmful, open a [Report a plugin](../../issues/new?template=report-plugin.yml) issue. For a security problem in a script plugin, use [private vulnerability reporting](../../security/advisories/new) instead.

## License

This repository's own files (documentation, tools, workflows, the Worker) are under the [MIT License](LICENSE). Each pack carries its own license, named in its `kando-plugin.json` and shown in Kando.
