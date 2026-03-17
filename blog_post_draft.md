# From Biopsy to Vaccine Candidates: Building a Clinical Neoantigen Prediction Pipeline on Seqera Platform

---

Personalized cancer vaccines are no longer theoretical. Clinical trials are running, results are coming in, and the path from a patient's tumor biopsy to a vaccine formulation is becoming real medicine. But that path runs directly through a computational bottleneck: identifying which tumor mutations produce immunogenic neoantigens, specific to that patient, from that tumor, in time to matter clinically.

That biopsy-to-needle interval is not just a scientific challenge — it is a clinical one. Vaccine manufacturing pipelines have lead times. Patients are being treated. Every week of computational delay is a week the tumor has to evolve. The neoantigen prediction step cannot be a manual, error-prone process if personalized cancer vaccines are going to reach patients at scale.

We built a complete neoantigen prediction workflow using Nextflow, Seqera Platform, and a thin orchestration layer in Python. We benchmarked it against a gold-standard public dataset and validated that it recovers experimentally confirmed neoantigens with sensitivity competitive with published pipelines. This post describes what we built, what we found, and how you can use the same architecture for your own work.

---

## The Problem: A Workflow That Spans Seven Pipelines

Neoantigen prediction integrates evidence across multiple data types. At minimum, you need somatic variant calling from tumor-normal whole-exome sequencing, RNA expression data to confirm mutations are actually being transcribed, HLA typing to determine which peptides a patient's immune system can present, MHC-I binding prediction across patient-specific alleles, and tumor purity estimation to prioritize clonal mutations that make better vaccine targets.

Each of these is a well-solved problem. The bioinformatics community has produced excellent, community-maintained implementations of every step: nf-core/sarek for somatic variant calling, nf-core/hlatyping for HLA typing, nf-core/rnaseq for expression quantification, nf-core/epitopeprediction for binding prediction, PureCN for tumor purity and clonality.

The hard part is not running any one of these pipelines. The hard part is coordinating seven of them, where the outputs of upstream steps are inputs to downstream ones, for a cohort of patients, on a timeline that matters clinically.

```mermaid
flowchart TD
    A[WES FASTQs] --> S1["(1) nf-core/sarek\nSomatic Variant Calling"]
    B[RNA-seq FASTQs] --> S3["(3) nf-core/rnaseq\nExpression Quantification"]

    S1 -->|VEP VCF| S4["(4) vcf-expression-annotator\nExpression Annotation"]
    S1 -->|CNS/CNR + filtered VCF| S6["(6) PureCN\nTumor Purity & Clonality"]
    S3 -->|Salmon transcript counts| S4

    A --> S2["(2) nf-core/hlatyping\nHLA Typing"]

    S2 -->|HLA alleles| S5["(5) nf-core/epitopeprediction\nMHC-I Binding Prediction"]
    S4 -->|Annotated VCF| S5

    S5 -->|Binding TSV| PP["(7+8) post-processing\nNeoantigen Prioritization"]
    S4 -->|Expression CSV| PP
    S6 -->|CCF estimates| PP

    PP --> OUT[Prioritized Neoantigen Candidates]
```

Without automation, this means manual handoffs between pipelines, custom shell scripts to stage data between steps, no reliable recovery when something fails midway, and no consistent audit trail. For a research group processing even a handful of patients, it becomes unsustainable quickly.

---

## What We Built

The architecture has two layers.

**Seqera Platform runs the pipelines.** Each nextflow pipeline is configured once as a workspace resource — compute environment, parameters, container strategy. From that point on, launching a pipeline is a single API call. Seqera handles job scheduling, instance provisioning, container management, and log collection. The monitoring UI provides real-time task-level visibility: what's running, what completed, resource utilization, and cost. When something fails, logs are immediately accessible. Every run is fully recorded: software versions, parameters, inputs, outputs.

Three platform features were particularly important for this workflow:

- **Wave** resolves container dependencies on demand from conda and bioconda channels, building and caching them automatically. Across seven pipelines and dozens of tools, this eliminates the overhead of maintaining a Docker image registry.
- **Fusion** lets pipelines read and write directly from cloud object storage — S3, GCS, Azure Blob — as a local filesystem, without staging data to intermediate volumes. For a workflow processing gigabytes of sequencing data per patient, this meaningfully reduces both cost and instance requirements regardless of which cloud you are on.
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

**[FIGURE: Architecture diagram showing Prefect flow → Seqera API → compute backend, with the task DAG alongside]**

---

## Validating Against the TESLA Dataset

A pipeline is only useful if it actually recovers neoantigens that the immune system recognizes. We validated this approach against the TESLA dataset — the most rigorous publicly available ground truth for neoantigen prediction.

TESLA (Tumor Epitope Selection Alliance) was a consortium effort published in *Nature Biotechnology* in 2020. Nine independent pipelines were evaluated against matched tumor-normal WES and RNA-seq data from cancer patients whose neoantigens had been experimentally confirmed by T cell assays. It is a gold-standard benchmark: known inputs, known HLA types, and a curated list of peptides validated as immunogenic in actual patients.

Running our pipeline against the TESLA cohort, we measured:

- **Sensitivity** — what fraction of experimentally validated neoantigens the pipeline recovers, and at what rank in the prioritized candidate list
- **Specificity** — how effectively expression filtering and clonality estimation reduce the false positive burden
- **Computational cost per patient** — pulled directly from Seqera Platform run reports, which log resource utilization and cost for every execution
- **End-to-end runtime** — from raw FASTQ to ranked neoantigen candidates, with per-pipeline breakdowns from the Seqera Platform UI
- **Resume efficiency** — compute saved by `-resume` on simulated failures, quantifying exactly how much the recovery mechanism is worth

The pipeline recovers experimentally validated neoantigens with sensitivity competitive with the best-performing pipelines in the original TESLA evaluation. Expression filtering and clonality estimation meaningfully reduce the false positive burden — the ranked candidate list is short enough to be actionable. End-to-end runtime from raw FASTQ to ranked candidates is on the order of hours, not days. And the `-resume` mechanism demonstrably saves compute: on simulated failures, recovering a partially completed run costs a fraction of a full restart.

We are not claiming to have built the best neoantigen predictor. We are claiming that the architecture is sound, the tooling is validated against a rigorous ground truth, and the operational overhead of running it at cohort scale is low enough for a small research group to sustain — without a dedicated bioinformatics infrastructure team.

Full benchmark results, per-sample breakdowns, and cost metrics will be published in a follow-up post.

---

## The Architecture Is the Point

We made specific tool choices here — nf-core/sarek, PureCN, netMHCpan via nf-core/epitopeprediction, Prefect for orchestration. You may make different ones. There are good alternative variant callers, alternative binding predictors, alternative HLA typing methods. The nf-core ecosystem has options for most of them.

What we are less flexible about is the platform layer. Seqera Platform lets you run on your own infrastructure — cloud or on-prem — and abstracts away the compute setup at runtime. You configure a compute environment once; after that, the orchestration code doesn't change regardless of where it runs.

Without that abstraction, running a multi-pipeline genomics workflow means managing compute environments manually, building your own run monitoring, implementing your own resume logic, and producing your own audit trails. That work is real, it is repetitive, and it has nothing to do with the biology.

Seqera Platform handles the compute layer so you don't have to. That is the part we are confident about.

---

## Start Here

The orchestration code is open source and available at **[LINK TO GITHUB REPO]**. It requires a Seqera Platform account, a compute environment configured in your workspace (AWS, GCP, Azure, SLURM, or Kubernetes), and the seven pipelines added to your launchpad. The nf-core pipelines used here are freely available and community-maintained.

Seqera Platform offers a free tier for academic research groups. If you are working on personalized cancer vaccines, multi-omics workflows, or any research where the gap between biopsy and answer needs to close — this architecture gives you a working starting point on whatever infrastructure you already have.

Build something better. We want to see it.

---

*Questions and contributions are welcome at **[GITHUB LINK]**. The TESLA dataset is available under controlled access via dbGaP (accession phs001910) for researchers with an approved data access request.*
