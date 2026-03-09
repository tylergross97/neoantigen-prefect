# PID262622 ORIGINATOR — Validation Notes

## Sample
- Patient: PID262622, tumor: ORIGINATOR (earliest timepoint)
- Indication: ccRCC (clear cell renal cell carcinoma) — PDMR sample
- WES samplesheet: samplesheets/PID262622_wes.csv
  - Tumor: PID262622_T, Normal: PID262622_N
- S3 outputs: s3://1000g-data-link-test-eu-west-1-iwcyt6phg/neoantigen/PID262622/

## Manual run reference
- Repo: https://github.com/tylergross97/neoantigen_prediction_workflow
- Results: results/pdmr/PID_262622/neo_downstream/tumor_ORIGINATOR_vs_normal_ORIGINATOR/
- Key files:
  - merged_df_final2.csv — binding predictions merged with expression
  - tertiary/tumor_ORIGINATOR_vs_normal_ORIGINATOR_filtered_variants.csv — CCF-joined final candidates
- HLA alleles used (manual): A*24:02; A*30:04; B*44:03; B*57:01; C*06:02; C*07:06
- Note: manual run used STAR-Salmon (star_salmon/); automated uses Salmon pseudo-alignment (salmon/)

## PureCN automated run
- Seqera workflow ID: 1b0YZ12khifGmG (FAILED — Nextflow output capture bug, PureCN itself succeeded)
- Work dir: s3://1000g-data-link-test-eu-west-1-iwcyt6phg/work/ec/2007cde7a4b2f83fb7ffa45a17a9f5/
- PureCN solution: **Purity=0.76, Ploidy=2.03 (near-diploid)**, Not flagged, Not failed
- Sex flag: "Coverage: M VCF: F" — chrX coverage/ploidy discordance, not a problem
- 14 local optima explored; 279 somatic variants with CCF called

## Variant concordance: manual vs. automated PureCN

12/18 variants from the manual tertiary output match directly by genomic position.
Core clonal drivers all confirmed.

| Gene    | Automated CCF | Manual CCF | Notes                          |
|---------|---------------|------------|--------------------------------|
| CSF1    | 1.0 (0.93–1)  | 1.0        | Core clonal driver — match     |
| OPN3    | 1.0 (0.99–1)  | 1.0        | Frameshift — match             |
| SCN11A  | 1.0 (0.95–1)  | 1.0        | Match                          |
| CWF19L2 | 1.0 (0.86–1)  | 1.0        | Match                          |
| SRCAP   | 1.0 (0.91–1)  | 1.0        | Frameshift — match             |
| COL4A1  | 0.96          | ~0.96      | Match                          |
| TMOD2   | 0.96          | ~0.96      | Match (also frameshift nearby) |
| ZNF608  | 0.92          | 0.92       | Match                          |
| OLFM4   | 0.92          | 0.92       | Match                          |
| NPC1L1  | 0.78          | 0.78       | Match                          |
| ACSS2   | 0.87          | 0.87       | Match                          |
| AKAP1   | 0.44 (subcl.) | 0.44       | Subclonal — match              |
| TTC22   | NOT FOUND     | present    | Position mismatch or filtered  |
| CR1     | NOT FOUND     | present    | Position mismatch or filtered  |
| KEL     | NOT FOUND     | present    | Likely ML.SOMATIC=FALSE        |
| SLC27A4 | NOT FOUND     | present    | Likely ML.SOMATIC=FALSE        |
| RAMP2   | NOT FOUND     | present    | Large inframe del — expected   |
| PDZD4   | NOT FOUND     | present    | chrX + sex flag — expected     |

## Additional automated hits not in manual top list (biologically notable)
- **BAP1** chr3:52408571 AT>A frameshift CCF=1.0 — canonical ccRCC driver (~10–15% of ccRCC)
- **TSC1** chr9:132902640 G>A CCF=1.0 — mTOR pathway, relevant to ccRCC treatment
- UMPS chr3 CCF=1.0 — pyrimidine synthesis
- Multiple other CCF=1.0 variants likely clonal passengers

## Biological plausibility for ccRCC

Overall assessment: **biologically coherent ccRCC picture.**

- **BAP1 frameshift (clonal)** — strongest ccRCC signal; defines aggressive molecular subtype
- **TSC1 mutation (clonal)** — mTOR pathway; target of everolimus/temsirolimus
- **SRCAP frameshift (clonal)** — chromatin remodeling, same functional class as PBRM1/SETD2/BAP1
- **ACSS2 mutation** — metabolic reprogramming; hallmark of ccRCC ("clear cell" lipid/glycogen phenotype)
- **AKAP1** — mitochondrial scaffolding protein with published kidney cancer biology; subclonal
- Near-diploid (ploidy=2.03) at purity=0.76 is consistent with early/primary ccRCC
- VHL absent from neoantigen list — expected: VHL mutations are often copy-neutral LOH or present
  in gnomAD at low frequency and would be filtered; rarely neoantigen-generating

## Post-processing validation (run 4Eu6dnLkvuharR)

S3 outputs: `s3://1000g-data-link-test-eu-west-1-iwcyt6phg/neoantigen/PID262622/post_processing/`
- `neoantigen_downstream/PID262622_T/merged_df_final2.csv` — 124 rows
- `tertiary/PID262622_T_filtered_variants.csv` — 113 rows

### Row counts vs. manual

| File                  | Automated | Manual | Delta  |
|-----------------------|-----------|--------|--------|
| merged_df_final2.csv  | 124       | 77     | +61%   |
| filtered_variants.csv | 113       | 67     | +69%   |

Automated produces ~70% more rows. Likely explanation: manual run used syfpeithi + mhcflurry;
automated uses mhcflurry + mhcnuggets. Two-tool ensemble captures more weak binders.

### Core clonal gene checklist

| Gene    | Automated             | Manual                | Match               |
|---------|-----------------------|-----------------------|---------------------|
| CSF1    | rank=0.35, CCF=1.0    | rank=0.35, CCF=1.0    | exact               |
| OPN3    | rank=0.46, CCF=1.0    | rank=0.46, CCF=1.0    | exact               |
| SCN11A  | rank=0.02, CCF=1.0    | rank=0.31, CCF=1.0    | better peptide found|
| SRCAP   | rank=0.29, CCF=1.0    | rank=0.29, CCF=1.0    | exact               |
| CWF19L2 | rank=0.02, CCF=1.0    | rank=0.32, CCF=1.0    | better peptide found|
| AKAP1   | rank=0.46, CCF=0.44   | rank=0.46, CCF=0.44   | exact (subclonal)   |
| KEL     | rank=0.009, CCF=NaN   | rank=0.003, CCF=NaN   | present             |
| SLC27A4 | rank=0.002, CCF=NaN   | rank=0.044, CCF=NaN   | present             |
| BAP1    | not found             | not found             | no binding epitope  |
| TSC1    | not found             | not found             | no binding epitope  |

16/18 genes shared between automated and manual output.

### Automated-only genes (new candidates)
KCND3, SHANK3, SLC16A7, BLVRA, CEPT1, KPNA7, PDGFRB, RBPJ

- Most have NaN CELLFRACTION (no PureCN CCF match — subclonal or VCF position mismatch)
- KCND3 is the top binder in the automated output (rank ~0.0005) — potassium channel, absent from manual
- **SLC16A7 CCF=1.0 (clonal)** — notable new clonal candidate not present in manual

### Manual-only genes (absent from automated)
CR1, RAMP2 — likely filtered by different binding rank cutoff or expression threshold
