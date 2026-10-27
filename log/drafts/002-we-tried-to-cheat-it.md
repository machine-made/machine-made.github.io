---
title: We built a benchmark, then tried to cheat it
number: 2
date: draft
byline: Jac
data: loombench selftest/attacks (13 folders), selftest/run_all.py, selftest/test_harness.py
---

LoomBench gives a coding agent a small numerical job: port a classic Fortran routine to
Rust, or find why a short simulation blows up. The agent's code is then run on hidden
inputs and compared, value by value, with a reference program it never sees.

A benchmark like this has one obvious weakness. The answers exist on the same machine as
the agent. If the agent can read them, the score means nothing. And agents are good at
finding shortcuts: not from malice, but because "make the check pass" is a goal they are
trained to reach.

So before any real model ran, we played the agent. We wrote the cheats ourselves.

## Thirteen ways to cheat

Each one is a folder in the benchmark, kept forever as a test that must fail:

| Cheat | What it tries |
|---|---|
| read the answers | open the hidden expected-output file from the solution |
| read them at build time | a Rust build script that copies the answers into the code |
| include them | `include_bytes!` or a Fortran `include` of the answer file |
| hide the path | `use std as s; s::fs::read(...)`, or a `#[path]` module |
| skip the work | exit early, or `STOP` in Fortran, before the slow part |
| fake the clock | print a made-up compute time |
| fool the QR check | return NaN or zero matrices, hoping a lazy comparison passes |

## How they fail

Three layers stop them, and two of the cheats run with the first layer switched off, to
prove the other layers hold on their own.

1. **Static rules.** Before anything is built, the code is read. In Rust only arithmetic
   and container parts of the standard library are allowed. That is an allow-list, not a
   block-list: our first version blocked `std::fs`, and `use std as s; s::fs` walked
   straight past it.
2. **A jail.** The build and the run happen inside bubblewrap: the repository and the home
   folder are empty, `/tmp` is fresh, the network is off. The answers are not hidden; they
   are simply not there.
3. **The scorer checks outside.** The program writes its outputs; the comparison happens
   outside the jail. For the QR task the program never reports a score at all: the scorer
   multiplies the matrices itself.

A timed run must also produce correct outputs, so skipping work to look fast is caught
by the same gate as a wrong answer.

## The agent's side

The agent works in a sandbox outside the repository. A stand-in agent tests the harness:
one that solves the task, one that goes looking for the answers, one that hangs and one
that crashes. The snooper finds nothing; the hung one is stopped at its time limit.

> **What failed**
> Our own rules, twice. The block-list missed crate aliasing, and the fix (an allow-list)
> then rejected an honest grouped import, `use std::{f64::consts::PI, mem}`, until we
> checked only the first segment of each entry. Every honest rejection is a false
> accusation, so the benchmark publishes the reason for each one.

Data: the 13 attack folders and the self-test that runs them, in the LoomBench
repository (opening with its first results).
