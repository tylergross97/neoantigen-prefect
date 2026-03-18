#!/bin/bash
nohup python run_patient.py PID147771 \
  --resume-workflow "nf-core/sarek:1ALdfrFAxhAPk7" \
  --resume-workflow "nf-core/rnaseq:28vkJjH2MRNBGS" \
  --resume-workflow "hlatyping:4QGfc9LY1NpPnE" \
  > neoantigen_147771.log 2>&1 &
echo "PID: $!"
