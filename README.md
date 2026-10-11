# Mersich Lab software site

This public website template contains two product pages: Superbench and Figure Tool. It does not include personal research pages, manuscript content, private reports, local QA evidence, or unpublished scientific assets.

The Figure Tool page is assembled from the immutable `1.0.0-beta.6` web release at the pinned GitHub release URL in [`config/figure-release.json`](config/figure-release.json). The SHA-256 value in that file must be filled from the exact release ZIP before building or deploying. The builder rejects a pending or malformed digest, verifies the archive bytes, and extracts only the `superbench/figure_tool/` subtree. It does not follow a floating `latest` release.

This directory is the standalone public-site repository template. From its root, run `python scripts/build_site.py`. For offline qualification, use `python scripts/build_site.py --archive <verified-local-figure-tool-web.zip>`. Both commands require a fresh `_site` output path; existing output is never deleted or overwritten. Generated output is ignored by Git.

The Pages workflow builds and tests this template, then deploys it through GitHub Pages when run from the public repository. This source template does not itself publish a release, change DNS, or contain a custom domain file. The template contains no personal research pages, manuscript content, private reports, local QA evidence, or unpublished scientific assets.
