# credit_report_llm

LLM-assisted credit report QA and extraction demo for structured querying, direct field extraction, and offline deployment.

## Overview

This repository currently maintains two parallel app variants:

- `credit_demo_2/`: the main development and local testing version
- `credit_demo_2_offline/`: the offline / intranet deployment version

The project focuses on two complementary flows:

1. Natural-language question -> controlled SQL planning -> structured query execution -> business-friendly answer
2. Extraction-style request -> targeted module retrieval -> structured field answer

## Repository Structure

- `credit_demo_2/`: primary app for iterative development
- `credit_demo_2_offline/`: offline runtime variant and offline dependency scripts
- `mapping/`: field mappings and code-table mappings
- `schema/`: report schemas
- `scripts/`: parsing and enrichment utilities
- `data_recource/`: local-only input materials directory, kept out of Git tracking
- `output/`: local-only generated artifacts directory, kept out of Git tracking

## Local Development

Start the development app:

```bash
cd credit_demo_2
pip install -r requirements.txt
BACKEND_PORT=8011 bash run.sh
```

Start the offline variant:

```bash
bash run_credit_demo_2_offline.sh
```

## Parsing Utilities

The utility scripts assume repository-root relative paths. Example:

```bash
python3 scripts/parse_individual_report.py \
  data_recource/individual.xml \
  -o output/individual.standard.json
```

## Data and Privacy Policy

Real report files, locally uploaded reports, and derived artifacts are intentionally excluded from Git tracking.

This includes:

- raw report inputs under `data_recource/`
- generated outputs under `output/`
- local built-in sample data under `credit_demo_2/data/builtin/`
- local offline data under `credit_demo_2_offline/data/`

If you want to run the full pipeline locally, place the required private files back into those directories on your machine only.

## Recommended Workflow

1. Develop and verify changes in `credit_demo_2/`
2. Port confirmed changes into `credit_demo_2_offline/` when needed
3. Keep offline dependency bundles local unless a deliberate release package is being prepared

## Notes

- Some code and docs still reference historical absolute `source_file` paths in generated artifacts; these are runtime-neutral and can be regenerated locally if needed.
- If the repository needs to become lighter later, the next cleanup target should be regenerable JSON artifacts and large binary reference files.
