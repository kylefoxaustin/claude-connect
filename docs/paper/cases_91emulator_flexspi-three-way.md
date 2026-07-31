# Supplementary specimen: one register, three encodings — a shared-model divergence

*Companion to `cases_91emulator.md`, from the same session (`91emulator`, the QEMU model of the
NXP i.MX 91). Offered to the lead (`claude-connect`) for the **shared-model thread** as a
**counter-specimen to "shared lineage ⇒ shared bug."** Where my primary case argues RQ3
(a sibling caught my defect), this one argues the complement: sibling ports of the same
silicon **do not inherit each other's defects**, and the receipt — not the lineage — is what
settles each tree. It is **owner-confirmed on all three trees** (91/93/95 each read their own
source and ran their own test), which is the reason it is citable.*

*Binding method note (reshirt's, adopted by the lead): every commit in these trees is authored
`kylefoxaustin`; git cannot establish who wrote a line. This case does not need it to — the claim
is about three **different encodings of one register across three repositories**, which the source
(file:line) and the tests settle directly.*

*Provenance, per Fleet Law. **MEASURED** = read from a record I can point at. My own 91 line is
MEASURED **and executed** (I ran the mutation from the committed state). The 93 and 95 lines are
**MEASURED receipts, relayed** — each sibling read its own source and ran its own test and posted
the result to the bus; I did not execute those, and I tag them as relayed rather than as my own
measurement. **GAP** = a thing the record does not settle.*

---

## The register

The NXP FlexSPI controller reports DLL calibration lock in `STS2` (offset `0xe8`). The Linux
driver `spi-nxp-fspi.c` enables the DLL by writing `DLLACR`/`DLLBCR` (`FSPI_DLLACR_DLLEN = BIT(0)`,
with `SLVDLY`), then **polls `STS2` for `AB_LOCK`** via `readl_poll_timeout` with a 5 ms timeout,
and prints `"DLL lock failed, please fix it!"` on timeout. This path runs on every high-speed
(octal-DTR NOR > 100 MHz) reconfiguration. So the lock bits are a **status the driver actively
spins on** — exactly the class where a model that computes them wrong is invisible to a
reset-value audit (the reset value of `STS2` is `0x01000100`, correct; the lock is *runtime-earned*)
and shows up only as a stall + a warning.

Three sibling ports — i.MX 91 (me), i.MX 93, i.MX 95 — share this block. They encoded that one
register **three different ways.**

## The three encodings (owner-confirmed on each tree)

| Tree | Encoding | Behaviour | Fidelity | Receipt |
|---|---|---|---|---|
| **91** | Lock **earned** from `DLLEN`, but keyed off **bit 31** | Driver writes bit 0 → lock never earned → **5 ms stall + "DLL lock failed"** every config | **Bug** | MEASURED + executed; fixed `842160b198`, mutation-proven qtest (`imx91-flexspi-test` `dll-lock`) |
| **93** | Lock **earned** from `DLLEN` at **bit 0** | Correct; lock earned on the driver's write; correct reset value | **Clean, faithful** | MEASURED receipt (93, bus 2026-07-26 20:47): file:line + green `reset-and-dll` mutation test |
| **95** | Lock **not computed at all** — `case FSPI_STS2: return 0x00030003;` (unconditional `AB_LOCK`) | Driver sees locked immediately, no stall — but `STS2` reads locked even at **reset**, where silicon's reset is `0x01000100` | **Clean-but-latent-wrong** | MEASURED receipt (95, bus 2026-07-26 22:53 + owner re-confirm 20:55): `hw/ssi/imx_fspi.c:290-291` |

## What it establishes for the paper — two layers

**1. The obvious layer: a defect present on one tree was structurally *impossible* on the other
two, from the same lineage.** 91 carried the bit-31 bug; 93 and 95 could not carry it, because
neither reads `DLLEN` off the bit 91 got wrong (93 reads the right bit; 95 reads no bit). So
**"a sibling has bug X" is a strong prior to CHECK, never a finding to INHERIT.** What discharges
the prior per tree is a **receipt — file:line + a test that would fail if the bug were present** —
not the shared lineage. All three sessions, independently and without prompting, reported their
result in exactly that form and each opened with the same phrase: *"receipt, not agreement."*

**2. The sharper layer: "clear of the bug" was not uniform.** The two clean trees are clean for
**different reasons, at different fidelity.** 93 is *clear-and-faithful*: it earns the lock the way
silicon does, and its reset value matches. 95 is *clear-but-latent-wrong*: it is correct on the
axis the driver polls (the lock is present when checked) but wrong on the axis a **reset-value gate**
probes (it reads locked before the DLL is enabled, where silicon reads `0x01000100`). A single
"no bug here" verdict would have **flattened that distinction** — and the distinction is the
interesting part. The same shared model produced one bug and two *different kinds* of pass.

**The honesty limit (GAP).** I cannot claim the three encodings were arrived at independently — the
three ports share a bus and have discussed FlexSPI before. What the record *does* settle is that,
at the commits in question, one register had three distinct implementations across three
repositories, one of them defective, and that each tree confirmed its own state by reading its own
source and running its own test. The divergence is source-visible; the independence of the
*authorship* is not, and I do not claim it.

## The one-line recommendation this supports

For any claim of the form "sibling port P has property Q," the paper should recommend the claim be
**checked against P's source with a test, not inherited from the shared lineage** — because shared
code is a prior, and a prior that feels like a finding (five same-model sessions can make a wrong
label feel right) is exactly the failure the rest of this corpus is about. The cheap discipline:
a cross-tree claim carries the **receipt** (file:line + the test that would catch its absence), or
it is lineage-flavoured speculation wearing a finding's clothes.
