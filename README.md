# Ian Mersich website

Ian Mersich's personal website, with research, publications and scientific software.

Visit [imersich.com](https://imersich.com/), explore [Research](https://imersich.com/research.html), or open [Resources / Software](https://imersich.com/software.html). [Figure Tool](https://imersich.com/superbench/figure_tool/) and [miRNA Predictor](https://imersich.com/superbench/mirna/) run in your browser.

## Build the website

This repository contains the personal pages under `pages/` and the GitHub Pages deployment configuration. From the repository root, run:

```powershell
python -m unittest discover -s tests
python scripts/build_site.py --output _site/local-build
```

The builder downloads the versioned Figure Tool and miRNA Predictor archives selected in [`config/`](config/), verifies their SHA-256 hashes, and extracts them under `superbench/figure_tool/` and `superbench/mirna/`. It requires a fresh output directory. For an offline build, supply the matching archives with `--archive <figure-tool-web.zip>` and `--mirna-archive <mirna-predictor.zip>`.

Pushes to `main` run the tests, build the site and deploy it through GitHub Pages. [`CNAME`](CNAME) configures the `imersich.com` domain. The deployment includes `pages/`, the selected browser-tool releases, their release records and license files.

## Tool sources and reuse

[Figure Tool's source repository](https://github.com/ian-mersich/superbench-figure-tool) contains its editor source and development instructions. The [miRNA Predictor releases](https://github.com/ian-mersich/ian-mersich.github.io/releases) include the browser application, fitted model, study results and their reuse terms. The [HSP90 Atlas](https://github.com/ian-mersich/hsp90-atlas-site) is maintained separately.

Website code uses [Apache-2.0](LICENSE). Tool code, model parameters, scientific resources and third-party dependencies retain the separate terms supplied with each release. The portrait and CV are supplied for display on Ian's website; the software license does not grant reuse rights to them. Research figures and comparison data retain their [CC BY 4.0 attribution and scientific notes](pages/assets/research/README.md).
