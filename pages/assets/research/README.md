# Research examples

These assets illustrate two projects described on the Research page.

## miRNA modeling and performance comparisons

`mirna-study-overview.svg` summarizes Ian Mersich's RNA-seq-to-mature-miRNA
study from the 23 October 2026 manuscript and scientific companion 1.16.2.
The manuscript is in preparation and has not been posted. Original artwork
and results are supplied by Ian Mersich under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

`mirna-study-comparisons.csv` contains the nine displayed means, six available
95% bootstrap intervals, populations, miRNA coverage and source-table
identifiers. TCGA compares original ridge gene-input models in pooled
cancer-excluded predictions. CPTAC-3 and liver compare final procedures within
their own populations. The final P1 fit is the released browser model, but the
app's Study results page retains earlier comparisons and miRNA sets.

CPTAC-3 cancer groups receive equal weight; its intervals use 2,000 within-cancer
case resamples. Liver intervals use 10,000 resamples of 16 depositor-order
tumor–adjacent pairs; patient pairing was not independently verified. Both
cohorts had been examined during development. SiCmiR's standardized scores
are assessed by correlation. These plots do not present an abundance-error
comparison with SiCmiR. Model development and RNA-only application are shown
separately. No models were fitted or predictions recomputed for this figure.

## miR-21 prediction example

`mir21-example.csv` contains all 32 hsa-miR-21-5p (MIMAT0000076) estimates from
the saved GSE176289 example used to check the released miRNA Predictor 1.0.2.
Rows retain input file order. `mir21-example.svg` plots those unchanged values.
The model estimates unique-only mature-miRNA abundance on a log2(CPM + 1) scale.
This example demonstrates output, not predictive accuracy, a measured biological
difference, or an independent validation cohort.

The [browser release](https://github.com/ian-mersich/ian-mersich.github.io/releases/tag/mirna-predictor-v1.0.2)
contains the application, fitted model, example inputs, study comparisons and reuse
terms. The website's plotting source is maintained in its coordinating workspace.

## Rosiglitazone and vincristine response

`iscience-graphical-abstract.jpg` and `iscience-figure6-hires.jpg` reproduce the
publisher's graphical abstract and high-resolution Figure 6 from:

Mersich I, Blagg BSJ, Ali A. Multi-omic integration identifies broad drug resistance
mechanisms and strategies to therapeutically reprogram cancer cells. *iScience*.
2026;29(1):114293. [doi:10.1016/j.isci.2025.114293](https://doi.org/10.1016/j.isci.2025.114293).

Original graphical abstract: https://ars.els-cdn.com/content/image/1-s2.0-S2589004225025544-fx1_lrg.jpg

Original Figure 6: https://ars.els-cdn.com/content/image/1-s2.0-S2589004225025544-gr6_lrg.jpg

Copyright 2025 The Authors. Reproduced under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
`drug-resistance-computational-to-experimental.svg` places the computational
portion of the graphical abstract beside Figure 6G–J. A labeled arrow identifies
rosiglitazone as a compound selected for experimental testing. SVG viewBoxes omit
the abstract's illustrative heatmap and the other Figure 6 panels. All source
pixels, selected plots, labels and data are unchanged. The website caption
supplies experimental conditions, replication and the link to the complete
published figure and legend.
