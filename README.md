# Ian Mersich public software website

This repository deploys the public landing page and Superbench overview at `imersich.com`, and consumes accepted Figure Tool and miRNA Predictor browser releases. Site-level identity and attribution use **Ian Mersich**. Personal research pages, manuscript content, private reports, and QA are maintained outside this public repository in the local website workspace.

[`config/figure-release.json`](config/figure-release.json) pins the immutable `1.0.0-beta.6` Figure web archive and SHA-256. The builder verifies its bytes and extracts only `superbench/figure_tool/`; it does not follow a floating latest release. [`CNAME`](CNAME) retains the approved `imersich.com` custom domain.

From this repository root:

```powershell
python -m unittest discover -s tests
python scripts/build_site.py
```

For offline qualification, supply a verified local archive with `python scripts/build_site.py --archive <figure-tool-web.zip>`. Output defaults to the ignored `_site/`; the builder requires a fresh output directory and never overwrites existing output.

The Pages workflow tests the consumer, builds the pinned release, and deploys pushes to `main`. Only this repository's `pages/`, the qualified tool subtree, license, release record, and approved domain enter the build. Local private previews and website coordination files are outside this checkout.

The miRNA Predictor consumer uses `config/mirna-release.json` when present. It requires publication clearance, an immutable owner GitHub release URL, the accepted P1 model identity, and a SHA-256 pin. Its flat distribution archive is assembled at `superbench/mirna/`; the Figure subtree remains unchanged. Use `python -m unittest discover -s tests` for all consumer checks, and `--mirna-archive <verified-local-zip>` for offline build verification. The release records expose each consumed version and archive digest separately.

Code, fitted-model parameters, and bundled scientific resources retain the distinct license scopes supplied by the tool's accepted release; the website's root license does not relicense them.

The canonical local checkout is `C:\Users\ianme\Desktop\Projects\website\public-site`. Figure Tool implementation and release preparation remain in `C:\Users\ianme\Desktop\Projects\superbench_figure_tool`; the older portable site template is retained in the website workspace's `archive/figure-site-template-beta6/`.
