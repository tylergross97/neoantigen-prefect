# From Tumor Biopsy to Neoantigen Candidates: Why Seqera Platform is Essential Infrastructure for Personalized Cancer Vaccine Research

---

## The Promise of Personalized Cancer Vaccines

Personalized cancer vaccines represent one of the most exciting frontiers in oncology. The premise is elegant: every tumor accumulates somatic mutations that produce aberrant proteins. When these mutant peptides are presented on the surface of cancer cells via MHC molecules, they can be recognized by the immune system as foreign — neoantigens. By identifying which neoantigens a patient's tumor is expressing and which their immune system is equipped to recognize, researchers can design vaccines that train T cells to target and destroy that specific tumor.

This is not a future promise. Clinical trials are underway. The results are early but striking. And the bottleneck is no longer biological — it is computational.

---

## The Computational Challenge

Predicting neoantigens from a patient sample requires integrating evidence across multiple data types and analysis steps. At a minimum, you need:

- **Whole-exome sequencing (WES)** of both the tumor and matched normal tissue, to identify somatic mutations that are specific to the tumor
- **RNA sequencing** of the tumor, to confirm that mutated genes are actually being expressed — an unexpressed mutation cannot produce a neoantigen
- **HLA typing**, to determine which MHC alleles the patient carries — this determines which peptides their immune system can present
- **MHC-I binding prediction**, to score which mutant peptides are likely to bind to the patient's specific HLA alleles with sufficient affinity to trigger an immune response
- **Tumor purity and clonality estimation**, to prioritize mutations that are present in the majority of tumor cells — clonal neoantigens make better vaccine targets than subclonal ones

Each of these steps is itself a non-trivial computational problem. Each has been addressed by specialized, well-validated bioinformatics tools. But none of them operates in isolation. The outputs of variant calling feed into expression annotation. HLA typing and expression annotation both feed into binding prediction. Clonality estimates are joined at the final prioritization step. The full workflow is a directed acyclic graph (DAG) with parallel branches that converge at multiple points.

**[FIGURE: Pipeline DAG showing the 7-step workflow with parallel branches and merge points]**

Running this pipeline for a single patient is not a matter of running one tool. It requires coordinating seven interdependent Nextflow pipelines, each consuming the outputs of upstream steps and producing inputs for downstream ones. Without automation, this means manual handoffs, custom shell scripts to stage data between steps, and no reliable way to recover when something fails partway through. For a research group processing even a handful of patients, this quickly becomes unsustainable.

---

## Why Nextflow Is Necessary But Not Sufficient

The bioinformatics community has largely converged on Nextflow as the standard for writing reproducible, scalable pipelines. The nf-core project has produced community-maintained, production-quality implementations of nearly every tool in the neoantigen prediction workflow: nf-core/sarek for somatic variant calling, nf-core/hlatyping for HLA typing, nf-core/rnaseq for transcript quantification, nf-core/epitopeprediction for binding prediction.

Nextflow solves the problem of running a single pipeline reliably. It handles parallelization within a pipeline, retry logic at the process level, and the `-resume` mechanism that allows a failed run to pick up from the last successful task rather than starting over. These are substantial advantages.

But Nextflow does not solve the problem of coordinating multiple pipelines whose outputs feed into each other. That dependency logic lives above Nextflow. And for a workflow like neoantigen prediction, that coordination layer is where the real operational complexity lives.

Without it, a researcher must:

- Manually monitor each pipeline run to know when it has finished
- Manually trigger downstream pipelines once their dependencies complete
- Manually handle failures — determine whether a failure was transient or permanent, decide whether to resume or restart, track which samples have been processed
- Do all of this consistently, for every patient, across a cohort

This is not a sustainable research practice. It is a full-time job.

---

## Seqera Platform: Making the Compute Layer Disappear

Seqera Platform addresses a different but equally important problem: the infrastructure required to actually run these pipelines at scale on cloud compute.

Running nf-core pipelines on AWS without a platform like Seqera requires configuring AWS Batch compute environments, managing IAM permissions, handling container registries, configuring Nextflow to use the right executor, and debugging cloud-specific failures that have nothing to do with biology. For a computational biologist, this overhead is a significant barrier.

Seqera Platform abstracts all of this. You configure a compute environment once — specifying the cloud provider, instance types, and storage settings — and from that point forward, launching a pipeline is a single action. Seqera handles job scheduling, instance provisioning, and log collection automatically.

Several platform features are particularly valuable for this workflow:

**Wave containers** eliminate the need to maintain a Docker image registry. Wave resolves software dependencies on demand from conda and bioconda channels, building and caching containers automatically. For a workflow spanning seven pipelines and dozens of tools, this is a meaningful reduction in maintenance burden.

**Fusion** enables pipelines to read and write directly from Amazon S3 as if it were a local filesystem, without staging data to EBS volumes first. For a data-intensive workflow processing gigabytes of sequencing data per patient, this reduces both cost and complexity. Pipelines that would otherwise require expensive high-memory instances for data staging can operate with leaner compute profiles.

**The monitoring UI** provides real-time visibility into every running pipeline: which tasks are running, which have completed, resource utilization, and cost. For a researcher without a dedicated DevOps team, this replaces the need to SSH into compute nodes to check on jobs. When something fails, the logs are immediately accessible through the UI, often making root cause analysis a matter of minutes rather than hours.

**Every run is fully auditable.** Parameters, software versions, configuration, and outputs are recorded for every execution. For research groups working toward clinical translation — where reproducibility and traceability are not optional — this is foundational infrastructure.

---

## Prefect: Coordinating Across Pipelines — Powered by the Seqera Platform API

Seqera Platform excels at running individual Nextflow pipelines with full operational visibility. But the neoantigen prediction workflow requires coordinating seven of them, with cross-pipeline dependencies that live above any single Nextflow execution. That coordination layer is where a general-purpose orchestration framework like Prefect adds value.

It is worth being precise about what Prefect is doing here — and what it is not. Prefect is not running Nextflow. It is not managing compute. It is not monitoring pipeline internals. All of that remains Seqera Platform's responsibility, and critically, it is Seqera Platform that makes this tractable. Prefect simply calls the Seqera Platform API: launch this pipeline, wait until it completes, then launch the next one. The entire coordination layer is approximately 300 lines of Python.

If you were to attempt the same cross-pipeline orchestration against raw open-source Nextflow — without Seqera Platform — you would need to manage process IDs or job scheduler states directly, build your own log aggregation, implement your own retry and resume logic against Nextflow's internal cache, and have no unified view of what is running or why something failed. Seqera Platform's API exposes all of this cleanly: pipeline status, workflow history, execution logs, and the session context needed to resume a failed run — all accessible programmatically. Prefect benefits from all of it.

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

This launches the first three pipelines in parallel — sarek, hlatyping, and rnaseq — waits for their completion via Seqera's API, then triggers downstream steps in dependency order. At every point, the Seqera Platform UI provides full visibility into what is running: task-level progress, resource utilization, cost, and logs. Prefect provides visibility into the meta-workflow: which pipelines have completed, which are pending, and the overall state of the patient's run. The two monitoring surfaces are complementary — one for the biology, one for the orchestration.

**[FIGURE: Architecture diagram showing Prefect flow → Seqera API → AWS Batch, with the task DAG alongside]**

Failure recovery illustrates this complementarity most clearly. Cloud pipelines fail — spot instances are reclaimed, transient errors occur, a tool encounters an edge case in a particular sample. Without Seqera Platform, determining what completed and what needs to be rerun requires digging into Nextflow's work directory cache manually. With Seqera Platform, every run's state and session context are queryable via API. When a Prefect task fails, it captures the Seqera workflow ID. On retry, Prefect calls the Seqera API to retrieve that run's session context and re-launches with `-resume` — Nextflow skips every already-completed task and picks up exactly where it left off. No manual intervention. No discarded compute.

---

## What This Unlocks

The practical effect of this architecture is that neoantigen prediction becomes operationally tractable for a research group without a large bioinformatics infrastructure team.

A new patient sample requires no manual steps beyond preparing the samplesheet CSVs and running the command above. The flow handles parallelism, dependency ordering, failure recovery, and output organization automatically. Results land in a structured S3 directory hierarchy organized by patient and pipeline step, ready for downstream analysis.

The same infrastructure scales to a cohort. Multiple flows can run simultaneously, each processing a different patient independently. The Seqera Platform UI provides a unified view of all running pipelines across the cohort. The Prefect UI provides a unified view of all orchestration flows.

For groups working toward clinical translation, the audit trail built into every Seqera Platform run provides the foundation for reproducibility documentation. Every pipeline execution is traceable to a specific software version, parameter set, and input dataset.

---

## Benchmarking Against the TESLA Dataset

A pipeline is only as useful as its ability to correctly identify neoantigens that the immune system actually recognizes. To rigorously validate this approach, we are benchmarking against the TESLA dataset — the most comprehensive publicly available ground truth for neoantigen prediction.

TESLA (Tumor Epitope Selection Alliance) was a consortium effort published in *Nature Biotechnology* in 2020 by Wells et al. Nine independent computational pipelines were evaluated against matched tumor-normal WES and RNA-seq data from cancer patients whose neoantigens had been experimentally validated by T cell assays. The result is a gold-standard dataset: known input sequencing data, known HLA types, and a curated list of peptides confirmed to be immunogenic in the actual patient.

Running this pipeline against the TESLA cohort will allow us to report:

- **Sensitivity** — what fraction of experimentally validated neoantigens does the pipeline recover, and at what rank in the prioritized candidate list?
- **Specificity** — how effectively does expression filtering and clonality estimation reduce the false positive burden?
- **Computational cost per patient** — pulled directly from Seqera Platform's run reports, which log resource utilization and cost for every execution
- **End-to-end runtime** — from raw FASTQ to ranked neoantigen candidates, with per-pipeline breakdowns visible in the Seqera Platform UI
- **Resume efficiency** — by comparing cost with and without `-resume` on a simulated failure, quantifying exactly how much compute the recovery mechanism saves

These results will be reported in a follow-up post. The TESLA dataset is available under controlled access via dbGaP (accession phs001910) for researchers with an approved data access request.

---

## Getting Started

The code for this orchestration layer is open source and available at **[LINK TO GITHUB REPO]**. It requires a Seqera Platform account, an AWS compute environment configured in Seqera, and the seven pipelines added to your workspace launchpad.

Seqera Platform offers a free tier for academic research groups. The nf-core pipelines used in this workflow are freely available and community-maintained.

For researchers working on personalized cancer vaccines or other multi-pipeline genomics workflows, this architecture represents a practical path from prototype to production — one where the computational infrastructure supports the science rather than competing with it for attention.

---

*The author is [NAME] at [INSTITUTION]. The pipeline DAG and orchestration code described in this post are available at [GITHUB LINK]. Questions and contributions are welcome.*
