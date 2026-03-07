# Building a Neoantigen Prediction Pipeline on Seqera Platform

---

Personalized cancer vaccines are no longer theoretical. Clinical trials are running. Results are coming in. And the computational bottleneck — identifying which tumor mutations produce immunogenic neoantigens in a specific patient — is one researchers are actively solving right now.

We built a complete neoantigen prediction workflow using Nextflow, Seqera Platform, and a thin orchestration layer in Python. We benchmarked it against a gold-standard public dataset. It performed well enough to build on. This post describes what we built, what we validated, and how you can use the same architecture for your own work.

---

## The Problem: A Workflow That Spans Seven Pipelines

Neoantigen prediction integrates evidence across multiple data types. At minimum, you need somatic variant calling from tumor-normal whole-exome sequencing, RNA expression data to confirm mutations are actually being transcribed, HLA typing to determine which peptides a patient's immune system can present, MHC-I binding prediction across patient-specific alleles, and tumor purity estimation to prioritize clonal mutations that make better vaccine targets.

Each of these is a well-solved problem. The bioinformatics community has produced excellent, community-maintained implementations of every step: nf-core/sarek for somatic variant calling, nf-core/hlatyping for HLA typing, nf-core/rnaseq for expression quantification, nf-core/epitopeprediction for binding prediction, PureCN for tumor purity and clonality.

The hard part is not running any one of these pipelines. The hard part is coordinating seven of them, where the outputs of upstream steps are inputs to downstream ones, across cloud infrastructure, for a cohort of patients.

**[FIGURE: Pipeline DAG showing the 7-step workflow with parallel branches and merge points]**

Without automation, this means manual handoffs between pipelines, custom shell scripts to stage data between steps, no reliable recovery when something fails midway, and no consistent audit trail. For a research group processing even a handful of patients, it becomes unsustainable quickly.

---

## What We Built

The architecture has two layers.

**Seqera Platform runs the pipelines.** Each nf-core pipeline is configured once as a workspace resource — compute environment, parameters, container strategy. From that point on, launching a pipeline is a single API call. Seqera handles job scheduling, instance provisioning, container management, and log collection. The monitoring UI provides real-time task-level visibility: what's running, what completed, resource utilization, and cost. When something fails, logs are immediately accessible. Every run is fully recorded: software versions, parameters, inputs, outputs.

Three platform features were particularly important for this workflow:

- **Wave** resolves container dependencies on demand from conda and bioconda channels, building and caching them automatically. Across seven pipelines and dozens of tools, this eliminates the overhead of maintaining a Docker image registry.
- **Fusion** lets pipelines read and write directly from S3 as a local filesystem, without staging data to EBS volumes. For a workflow processing gigabytes of sequencing data per patient, this meaningfully reduces both cost and instance requirements.
- **The API** exposes pipeline status, run history, execution logs, and the session context needed to resume a failed run — all programmatically. This is what makes the orchestration layer possible.

**A thin Python layer coordinates across pipelines.** The cross-pipeline dependency logic — launch sarek, hlatyping, and rnaseq in parallel; wait for completion; trigger downstream steps in order — lives in approximately 300 lines of Python using Prefect. It is not managing compute. It is not monitoring pipeline internals. It calls the Seqera Platform API: launch this pipeline, wait until it completes, then launch the next one.

The result is a single command that processes a patient end-to-end:

```bash
python run_flow.py \
  --patient-id PID001 \
  --wes-samplesheet samplesheets/PID001_wes.csv \
  --hlatyping-samplesheet samplesheets/PID001_hlatyping.csv \
  --rnaseq-samplesheet samplesheets/PID001_rnaseq.csv \
  --tumor-sample PID001_T_vs_PID001_N \
  --sex XX
```

Failure recovery is handled cleanly. When a Prefect task fails, it captures the Seqera workflow ID. On retry, it retrieves the run's session context via the API and re-launches with `-resume` — Nextflow skips every already-completed task and picks up exactly where it left off. No manual intervention. No discarded compute.

**[FIGURE: Architecture diagram showing Prefect flow → Seqera API → AWS Batch, with the task DAG alongside]**

---

## Validating Against the TESLA Dataset

A pipeline is only useful if it actually recovers neoantigens that the immune system recognizes. We validated this approach against the TESLA dataset — the most rigorous publicly available ground truth for neoantigen prediction.

TESLA (Tumor Epitope Selection Alliance) was a consortium effort published in *Nature Biotechnology* in 2020. Nine independent pipelines were evaluated against matched tumor-normal WES and RNA-seq data from cancer patients whose neoantigens had been experimentally confirmed by T cell assays. It is a gold-standard benchmark: known inputs, known HLA types, and a curated list of peptides validated as immunogenic in actual patients.

Running our pipeline against the TESLA cohort, we measured:

- **Sensitivity** — what fraction of experimentally validated neoantigens the pipeline recovers, and at what rank in the prioritized candidate list
- **Specificity** — how effectively expression filtering and clonality estimation reduce the false positive burden
- **Computational cost per patient** — pulled directly from Seqera Platform run reports, which log resource utilization and AWS cost for every execution
- **End-to-end runtime** — from raw FASTQ to ranked neoantigen candidates, with per-pipeline breakdowns from the Seqera Platform UI
- **Resume efficiency** — compute saved by `-resume` on simulated failures, quantifying exactly how much the recovery mechanism is worth

The pipeline performed well enough to be a credible starting point for a production neoantigen prediction system. We are not claiming to have built the best neoantigen predictor. We are claiming that the architecture is sound, the tooling is validated, and the operational overhead of running it is low enough that a small research group can sustain it.

The specific numbers, along with a breakdown by TESLA sample, will be published in a follow-up post.

---

## The Architecture Is the Point

We made specific tool choices here — nf-core/sarek, PureCN, netMHCpan via nf-core/epitopeprediction, Prefect for orchestration. You may make different ones. There are good alternative variant callers, alternative binding predictors, alternative HLA typing methods. The nf-core ecosystem has options for most of them.

What we are less flexible about is the platform layer. Running a multi-pipeline genomics workflow on cloud infrastructure without Seqera Platform means managing compute environments manually, building your own run monitoring, implementing your own resume logic, and producing your own audit trails. That work is real, it is repetitive, and it has nothing to do with the biology.

Seqera Platform makes the compute layer disappear. That is the part we are confident about.

---

## Start Here

The orchestration code is open source and available at **[LINK TO GITHUB REPO]**. It requires a Seqera Platform account, an AWS compute environment configured in your workspace, and the seven pipelines added to your launchpad. The nf-core pipelines used here are freely available and community-maintained.

Seqera Platform offers a free tier for academic research groups. If you are working on personalized cancer vaccines, multi-omics workflows, or any research that requires coordinating multiple pipelines across cloud infrastructure, this architecture gives you a working starting point.

Build something better. We want to see it.

---

*Questions and contributions are welcome at **[GITHUB LINK]**. The TESLA dataset is available under controlled access via dbGaP (accession phs001910) for researchers with an approved data access request.*
