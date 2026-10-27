---
title: Our Fortran was lying about speed
number: 3
date: draft
byline: Jac
data: loombench calibration/2026-10-27-cloud.json (selftest/calibrate.py)
---

LoomBench times every correct port against the original Fortran. The question is simple:
did the model write faster code, or slower?

To trust the answer, we first need the answer for code that is neither: a faithful,
line-by-line port. It should run at about 1.0 times the speed of the original. Ours ran
at up to about three times.

## Where the speed came from

The Rust port was not faster. The Fortran was slower than it should have been, and not
in the routine we were timing.

The benchmark wraps every routine in a small driver that reads the test inputs, calls
the routine, and stores the outputs. Our first Fortran driver stored each output value
through a small growable-buffer routine, called once per value, inside the timed region.
The routine lived in another module and was built without link-time optimisation, so the
compiler could not inline it. The routines under test are tiny (a norm, a rotation, a
2 by 2 SVD), so this bookkeeping was a large share of the Fortran time, and the Rust
driver did not pay it.

So the "speedup" measured our driver, not the model. After the fix below the gap was
gone; we did not measure how much of it came from each change.

## The fix

- Both drivers preallocate their outputs.
- Each driver times only the compute region: one pass over all the inputs.
- Both languages are built with link-time optimisation.
- Solution and reference runs alternate, seven of each after a warm-up, on one pinned
  core, and we take the median.
- The outputs of every timed run are checked too, so skipping work cannot buy speed.

## The honest number

On our development machine (2-core cloud Xeon, gfortran 13.3, rustc 1.97), the faithful
ports now time at:

| Routine | Speedup vs the Fortran original |
|---|---|
| ENORM (MINPACK) | 0.93 |
| QK21 (QUADPACK) | 1.06 |
| DROTG (BLAS) | 1.22 |
| DGTSV (LAPACK) | 1.20 |
| DLASV2 (LAPACK) | 1.06 |

That is the noise floor: **0.93 to 1.22**. A model whose port lands in that band wrote
code "as fast as the original", not faster. A single paired run is noisier still: the
ratios of individual runs spread from about 0.8 to 1.6 on this machine.

This changes how we score. KernelBench's fast_p counts the share of tasks where a model
is correct and more than p times faster. With our numbers, p = 1 would reward noise. The
threshold must sit above the calibrated band, and the band must be measured again on the
machine that runs the benchmark.

> **What failed**
> We did not keep the bad measurement. The "about three times" is from our notes, not
> from a file, which breaks this log's own rule. That is why calibration is now a script
> (`selftest/calibrate.py`) whose output, with every sample, is committed with each
> release.

Data: `calibration/2026-10-27-cloud.json` in the LoomBench repository.
