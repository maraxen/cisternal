<!-- decision-matrix version: jury-adjudicated=2026-08-13; jurors=3; lenses=security-maintenance,delivery-speed,license-ip -->

# The customization decision matrix

Six ways to acquire functionality that already exists somewhere else: **accept a dependency**,
**vendor** it, **cherry-pick** from it, **re-implement** it, **derive inspiration** from it (design
only, no code), or **derive lessons** from it (process only, no code or design). Every option
was researched independently — grounded arguments for and against, with citations — then
adjudicated by three independent jurors, each reasoning through a different lens (supply-chain
security and maintenance burden; delivery speed and engineering cost; license/IP cleanliness).
The verdicts below are what all three lenses converged on, or explicitly disagreed about.

**How to use this**: for a routine decision, read the option's `Recommend when` / `Avoid when`
below and move on — that's the point of pre-adjudicating this once. For a genuinely novel or
high-stakes case (the option chosen will be hard to reverse, or the situation doesn't cleanly
match any bullet), run a fresh jury per the SKILL.md workflow instead of pattern-matching against
stale examples. Every claim below keeps its citation — don't strip them when quoting this doc
elsewhere; the citation is what makes the claim checkable rather than asserted.

Priority weight is the jury's 1–5 average of "how strongly should this be reached for by
default, all else equal" — not a ranking of which option is objectively best; a low-weight
option is often still the *right* choice in the specific situation its `Recommend when` names.

---

## Accept dependency

*Take the external package as a direct dependency via your package manager.*
**Priority weight: 3.3/5 · Jury confidence: 0.72**

**Recommend when:**
- The functionality is widely-adopted, actively-maintained infrastructure where community
  scrutiny and pooled funding (e.g. the post-Heartbleed Core Infrastructure Initiative) genuinely
  concentrate patching effort beyond what your team could sustain alone.
- The functionality is commodity/non-differentiating, an actively-maintained package already
  exists, and you need it working now rather than in weeks.
- The package is actively-maintained, permissively-licensed (MIT/Apache/BSD), **and** its full
  transitive dependency graph has actually been scanned and shown license-clean — not just
  eyeballed at the top level.

**Avoid when:**
- The package is small, thinly-maintained, or deep in a large transitive closure — left-pad,
  event-stream, and xz-utils all show trivial or trusted-seeming packages becoming single points
  of failure or multi-year-planted backdoors.
- The functionality is core to your competitive differentiation, or the dependency's trust/
  security posture is unacceptable for your context.
- You cannot or will not audit the transitive closure — dependencies can silently pull in
  copyleft/incompatible licenses even when the direct dependency looks clean.

**Jury dissent:** the risk isn't just the package you pick but its unauditable transitive closure
and registry trust model (Log4Shell, dependency confusion) — even a careful call inherits risk
invisible at adoption time. This risk is largely tooling-solvable (SBOM/license scanners,
Dependabot-style graphs) rather than structural; weight would rise paired with a mandatory
license-scan gate at adoption time.

<details>
<summary>Supporting evidence (citations)</summary>

**For:** "Don't reinvent the wheel" is the default engineering discipline, not a shortcut —
67 Bricks Engineering Blog, "Coding principles 6: Don't reinvent the wheel"
(blog.67bricks.com/?p=783). Linus's Law — widely-used dependencies get community scrutiny at a
scale no single team matches — Wikipedia, "Linus's law" (en.wikipedia.org/wiki/Linus%27s_law),
from Eric S. Raymond, *The Cathedral and the Bazaar* (1999). The demand-side replacement value of
widely-used OSS is estimated at $8.8T, with firms needing 3.5x more spend to build it in-house —
Hoffmann, Nagle & Zhou, "The Value of Open Source Software," HBS Working Paper 24-038 (Jan 2026)
(hbs.edu/faculty/Pages/item.aspx?num=65230). Post-Heartbleed, the Core Infrastructure Initiative
got AWS/Google/Microsoft/IBM/Cisco to each pledge $100k/yr for full-time OpenSSL maintainers —
Wikipedia, "Core Infrastructure Initiative." A single vetted implementation is a smaller
aggregate attack surface than N independent reimplementations — Zimmermann et al., "Small World
with High Risks," USENIX Security '19 (arxiv.org/abs/1902.09217). NIH syndrome carries its own
documented cost in re-derived edge cases and slower delivery — The Engineering Manager, "Not
invented here, revisited."

**Against:** left-pad (11 lines) broke Facebook/Netflix/Airbnb builds in 2016 — Wikipedia, "Npm
left-pad incident." event-stream (2018): a maintainer-trust compromise harvested Bitcoin wallet
keys across ~8M downloads before detection — Snyk, "A post-mortem of the malicious event-stream
backdoor." xz-utils (CVE-2024-3094): ~2 years of credibility-building before an SSH backdoor,
caught by chance days before reaching stable distros — Wikipedia, "XZ Utils backdoor." The
average npm package pulls ~80 transitive deps from ~39 maintainer accounts — Zimmermann et al.,
USENIX Security '19. Log4Shell (CVSS 10.0) had an unscopable blast radius precisely because real
exposure was defined by the full transitive tree — Rapid7, "Guide to Log4Shell." A 2024 Synopsys-
adjacent audit found 53% of examined commercial codebases had OSS license conflicts — Black Duck,
"Mastering Open Source License Compliance & Dependencies." Dependency confusion (2021) got
build systems at 35+ companies to auto-execute unvetted code — Alex Birsan, "Dependency
Confusion" (Medium). Sonatype logged 245,032 malicious packages in 2023 alone, more than
2019–2022 combined — Sonatype, "State of the Software Supply Chain." Joel Spolsky's
counter-argument: ceding a differentiator to an externally-controlled dependency is a strategic
risk, not just a technical one — "In Defense of Not-Invented-Here Syndrome" (2001).
</details>

---

## Vendor

*Copy the dependency's source directly into your repo, frozen at a point in time.*
**Priority weight: 3.7/5 · Jury confidence: 0.67**

**Recommend when:**
- You need hermetic, reproducible builds and isolation from live-registry attacks or unpublish
  events (left-pad) or in-flight compromise windows (xz-utils, event-stream) — **and** you have
  the resourcing to run vendoring with an explicit resync/audit cadence, the way Google or
  Kubernetes do.
- You need a fast, one-time integration whose result should also be hermetic and immune to
  upstream disappearance or mutation — `cargo vendor` and `go mod vendor` treat this as a
  legitimate, supported reproducibility mechanism, not a workaround.
- You need a frozen, single-location copy specifically so license/attribution review is
  tractable at scale.

**Avoid when:**
- Your team lacks the discipline to keep the vendored copy current — a bundled CVE fix becomes a
  manual per-copy hunting problem, and vendored code silently falls out of Dependabot-style
  scanning until someone stumbles on it, versions behind.
- (Same discipline gap, license angle) — vendoring converts license/attribution compliance from
  ecosystem-tracked metadata into permanent first-class maintenance work the project now owns
  outright.

**Jury dissent:** freezing a snapshot can just as easily freeze in a known-bad or pre-fix version
as protect against a future-bad one — vendoring has no advisory-feed analog telling you it's
time to re-vendor. The integration itself is fast, but the real cost (re-syncing, re-patching)
is deferred maintenance debt that reads worse a year later. "Most teams don't have the discipline
to keep vendored dependencies current" — the audit benefit is only real if someone actually
sustains it.

<details>
<summary>Supporting evidence (citations)</summary>

**For:** Vendoring gives hermetic, reproducible builds with no network dependency at build time —
Google's stated reason for requiring all non-Google code in `//third_party`
(opensource.google/documentation/reference/thirdparty). It isolates from registry-level
failure/attack — the left-pad incident is the canonical cited example
(en.wikipedia.org/wiki/Npm_left-pad_incident). `cargo vendor` / `go mod vendor` are first-class,
supported toolchain subcommands, not workarounds (doc.rust-lang.org/cargo/commands/cargo-vendor.html;
go.dev/ref/mod). A project vendored pre-compromise would not have ingested the event-stream or
xz-utils backdoors on its next build. Centralizing third-party code makes license auditing
tractable at scale (opensource.google/documentation/reference/thirdparty/android). Vendoring
preserves "hermeticity — absolute certainty about what code runs," the deliberate choice of
disciplined projects like Google and Kubernetes (nesbitt.io/2026/02/10/lockfiles-killed-vendoring.html).

**Against:** Bundled deps lose automatic security updates — a single upstream fix becomes
"hunting all affected [copies]" across the codebase (Gentoo, "The modern packager's security
nightmare," blogs.gentoo.org/mgorny/2021/02/19). Locally-modified vendored code is hard to resync
against upstream and can silently fork. Vendoring bloats repos and obscures diffs — Chromium
maintains dedicated tooling just to manage `third_party` bloat
(chromium.googlesource.com/chromium/src/+/HEAD/docs/adding_to_third_party.md). Automated security
tooling (Dependabot) is built around package-manager metadata, not vendored source — vendored
code generally can't be scanned without extra configuration (nesbitt.io). Vendoring internalizes
license/attribution obligations (NOTICE files, copyright headers) as first-class ongoing repo
maintenance (legalclarity.org; aboutcode.org). "Most teams don't have the discipline to keep
vendored dependencies current... [they] go stale quietly until someone discovers a CVE six
versions behind" (nesbitt.io).
</details>

---

## Cherry-pick

*Extract and adapt only the specific piece you need, not the whole dependency.*
**Priority weight: 2.3/5 · Jury confidence: 0.67**

**Recommend when:**
- You need one small, well-understood, self-contained piece of functionality, and taking the
  whole library (plus its transitive closure) would expose you to more maintainer-trust risk
  than the extraction is worth.
- Only a small, well-scoped piece is needed and pulling the whole package (avg. ~80 transitive
  deps for an npm package) would cost more integration/audit effort than a narrow, reviewed
  extraction.
- You're extracting a genuinely tiny, permissively-licensed snippet where de minimis copying
  doctrine plausibly applies, and you retain the attribution notice inline at extraction time.

**Avoid when:**
- The code you're extracting has non-obvious invariants or context-dependent behavior you don't
  fully understand — the canonical failure is Debian's 2006 OpenSSL patch, where maintainers
  stripped lines they mistook for uninitialized-memory noise and crippled the PRNG for two years
  (CVE-2008-0166). This is the single starkest cautionary case in this whole matrix.
- The extracted code will need upstream security/bugfix tracking over time with no resync
  tooling in place.
- The source is GPL/AGPL-licensed — pasting copyleft-licensed source is one of the most
  unambiguous ways to trigger the obligation to release the combined work under the same
  license, and ad hoc extraction empirically tends to drop the license headers that would even
  flag this.

**Jury dissent:** extraction drops the license/attribution metadata package managers track
automatically. The Debian OpenSSL PRNG incident shows extraction-without-context can silently
drop load-bearing logic — a "quick cherry-pick" can become a correctness investigation that
erases the speed advantage. Under a license/IP lens, this is the weakest option on the list: it
combines real copyleft-trigger risk with loss of the structured metadata whole-dependency or
vendoring approaches at least provide.

<details>
<summary>Supporting evidence (citations)</summary>

**For:** Every dependency taken on is attack surface; cherry-picking prunes unused code/features
by construction (Chainguard, "How to prevent software supply chain attacks"). Google's own SWE
guidance explicitly discourages a full dependency just to save a few lines of code (Winters,
Manshreck & Wright, *Software Engineering at Google*, ch. 21, abseil.io/resources/swe-book).
Depending on a whole package exposes you to its entire future, including a maintainer compromised
after the fact (event-stream, xz-utils) — a one-time reviewed extraction is not exposed to that.
US copyright's de minimis doctrine: courts have found copying as small as 30 characters out of 50
pages of code to be de minimis (*Vault Corp. v. Quad Software*, discussed in NYU JIPEL,
"Clarifying the De Minimis Doctrine in Copyright Law").

**Against:** Extracted/vendored code doesn't update itself — fixes made upstream after extraction
must be manually noticed and reapplied (dfetch docs, "Vendoring"). Because extracted code is easy
to change locally, teams are tempted to patch in place rather than upstream, accelerating drift
(Onur Solmaz, "Semantic vendoring"). Copy-based reuse routes around license-tracking tooling and
empirically drops attribution, leaving "orphaned" untracked code segments (Jahanshahi, Vasilescu
& Mockus, "Ensuring Open Source Integrity," arxiv.org/pdf/2606.23495). MIT's license text still
requires the copyright/permission notice "in all copies or substantial portions" — cherry-picking
doesn't exempt you, it just makes forgetting easier. GPL/AGPL's copyleft obligation triggers on
the act of copying itself. The canonical real-world correctness disaster: Debian's 2006 OpenSSL
PRNG patch (CVE-2008-0166), which made SSL/SSH keys on Debian-derived systems predictable for
~2 years (Sept 2006–May 2008) — Debian Security Advisory DSA-1571-1.
</details>

---

## Re-implement

*Build the functionality from scratch, owning the whole implementation — including the specific
case of rewriting a stable Python module in Rust behind a pyo3 interface.*
**Priority weight: 2.7/5 · Jury confidence: 0.58**

**Recommend when:**
- The functionality sits on a security-critical trust boundary where owning the full attack
  surface beats depending on an external maintainer pipeline that can be patiently compromised
  (xz-utils's ~2-year credibility-building backdoor) — **and** you can sustain it long-term, not
  just build it once.
- The functionality is small enough to build quickly **and** either core to your differentiation
  or blocked by an architectural ceiling no existing option can clear — Ruff (~1000x faster than
  the flake8/pylint stack), Polars (5–10x faster than pandas), and ripgrep (SIMD + work-stealing
  + gitignore-aware skipping) are all evidence that some gains are only reachable by rewrite, not
  incremental tuning.
- The functionality is core/differentiating and can be built genuinely from a spec or
  requirements list rather than by reading and porting the original's source line-by-line, so no
  direct-copying obligation ever attaches.

**Avoid when:**
- The target is a mature, heavily-used system whose "ugly" edge-case handling is load-bearing
  (Hyrum's Law) — a clean rewrite risks reintroducing already-fixed bugs, as Netscape's ~3-year
  4.0→6.0 rewrite illustrates (widely credited with ceding the browser market). A Rust/FFI
  rewrite specifically can introduce **new** unsoundness classes the original never had — pyo3's
  own issue tracker records real bugs in its panic-catching machinery at the FFI boundary.
- A working dependency already covers the need — a full rewrite is a multi-month-to-multi-year
  detour during which competitors keep shipping.
- "Reimplementation" in practice means closely reading and porting the original's source without
  clean-room separation — that blurs into the same substantial-similarity exposure as
  cherry-picking, minus even the attribution tooling package managers or vendoring provide.

**Jury dissent:** maintenance dominates lifecycle cost, and a *successful* rewrite can still fail
organizationally — one documented case (94% resource-usage win) cost the engineer their job by
concentrating irreplaceable knowledge in one person. For most needs this is close to the worst
short-term-speed option on the list; it only rises where the payoff (differentiation or 10x+
performance) justifies the schedule cost. The evidence set for this option is mostly about
engineering cost/quality, not IP risk directly — the license-lens verdict is a lower-confidence
extrapolation than the others.

<details>
<summary>Supporting evidence (citations)</summary>

**For:** For a core business function, "do it yourself, no matter what" — Joel Spolsky, "In
Defense of Not-Invented-Here Syndrome" (2001). Ruff is ~1000x faster than flake8/pylint; Polars
runs 5–10x faster than pandas — "UV and Ruff" (devtoolsacademy.com); "Python at 10×: Polars,
PyO3, and the Death of the Slow Path" (Medium). Pydantic v2 rewrote its validation core in Rust
(pydantic-core, via PyO3) explicitly to reduce bugs and improve corner-case handling, not just
speed — Pydantic team, "Introducing Pydantic V2" (pydantic.dev/articles/pydantic-v2). Fewer
self-owned dependencies mean a smaller attack surface, per event-stream and xz-utils. Prisma's
purpose-built rewrite cut bundle size ~90% (14MB→1.6MB) and made queries up to 3.4x faster by
dropping generality it no longer needed — Prisma, "Rust to TypeScript Update." ripgrep's speed
over grep comes from architectural choices (SIMD regex, work-stealing parallelism,
gitignore-aware skipping) that aren't tuning knobs available within grep's own architecture —
BurntSushi, "ripgrep is faster than {grep, ag, ...}."

**Against:** Rewriting a working system from scratch is "the single worst strategic mistake" a
company can make — Joel Spolsky, "Things You Should Never Do, Part I" (2000), on Netscape's
~3-year 4.0→6.0 rewrite. "Rewrite it in X" projects more often disappoint than delight across
eras (Rails→Node.js, Node.js→Go) — Herb Caudill, "Lessons from 6 software rewrite stories."
PyO3-based interop has documented soundness pitfalls: it's UB for a Rust panic to unwind across
the FFI boundary, and PyO3's own tracker records real bugs in its panic-catching machinery
(GitHub issues #492, #2501). Hyrum's Law: with enough users, every observable behavior —
including undocumented quirks and bugs — ends up depended on by someone, so a clean-room rewrite
satisfying only the documented spec is likely to break real users the original quietly
accommodated. Maintenance, not initial construction, dominates lifecycle cost — often several
times the build cost over the system's life (builtin.com, "You Should Be Wary Of Software
Dependencies"). Russ Cox: the industry's dependency-risk problem is mostly one of governance, not
reuse itself — better vetting and pinning, not reflexive reimplementation ("Our Software
Dependency Problem," research.swtch.com/deps). Prisma later retreated from its own Rust binary
specifically because cross-platform native builds and edge-runtime incompatibility (Cloudflare
Workers, Vercel Edge) created deployment complexity a same-language rewrite avoided — a pyo3-
style rewrite can trade a dependency-management problem for a harder polyglot build problem. A
documented Rust rewrite delivered 94% memory reduction and 79% latency reduction but made the
engineer the sole expert and single point of failure — and ultimately cost them their job.
</details>

---

## Derive inspiration

*Study the external project's design/architecture/API shape and build your own independent
implementation informed by it — no code copied.*
**Priority weight: 3.0/5 · Jury confidence: 0.58**

**Recommend when:**
- You want the design benefit of a proven external architecture with zero code-level
  supply-chain exposure and reduced IP risk — no package, no transitive tree, no maintainer-
  trust surface. Clean-room-style independent creation has been accepted as evidence of
  independent creation by US courts since *NEC v. Intel* (1989).
- You plan to write your own implementation regardless (legal posture or fit-to-your-callers
  reasons) and want the design pre-validated against a proven shape before you start.
- You want the strongest legally-recognized IP posture short of full independence — the Altai
  abstraction-filtration-comparison test and *Google v. Oracle*'s fair-use holding both support
  reimplementing a design's structure or interoperability shape without copying literal code.

**Avoid when:**
- The original's specific, odd-looking implementation choices encode hard-won incident
  knowledge (Chesterton's Fence) that a design-only study won't surface — or your team lacks the
  capacity to build and then indefinitely maintain the reimplementation itself.
- You need working, running functionality immediately — studying the design doesn't shortcut
  writing and testing the implementation, and the "second-system effect" warns that the extra
  design freedom this path grants tends toward scope creep, adding time rather than saving it.
- You're treating an informal "read the code, then write my own" pass as equivalent to
  legally-recognized clean-room protection — genuine clean-room requires two separated teams (a
  spec-writing team with code access, an implementing team without), and even *Oracle v. Google*
  explicitly declined to resolve whether API structure is copyrightable at all, resting solely on
  fair use.

**Jury dissent:** true clean-room protection requires genuinely separated teams and a written
spec, not just casual reading of the original's code — a casual version earns less legal and
epistemic protection than it feels like it does. Through a pure speed lens this barely
outperforms plain reimplementation — the legal/design-quality upside is real but mostly
orthogonal to how fast you ship.

<details>
<summary>Supporting evidence (citations)</summary>

**For:** Clean-room / independent-creation methodology has been accepted as evidence of
independent creation by US courts since *NEC v. Intel* (1989) — Wikipedia, "Clean-room design."
Studying architecture/API shape targets the layer copyright treats as least protectable (ideas,
functional requirements, interoperability structure) — *Computer Associates v. Altai*, 982 F.2d
693 (2d Cir. 1992), the abstraction-filtration-comparison test. *Google LLC v. Oracle America*,
593 U.S. ___ (2021): reimplementing the declaring code of 37 Java SE APIs was held fair use (6–2)
— but the Court explicitly declined to resolve API copyrightability itself. Independent
implementation lets you calibrate to your own callers — Joshua Bloch, "How to Design a Good API
and Why it Matters" (OOPSLA 2006). Studying external design as informed input is the literature's
documented antidote to NIH syndrome — Katz & Allen, *R&D Management* 12(1), 1982.

**Against:** A rewrite — even an independently-designed one — discards hard-won edge-case
knowledge; Netscape's ~3-year 4.0→6.0 rewrite is the canonical case (Spolsky, "Things You Should
Never Do, Part I"). The "second-system effect": a successor design, freed from prior constraints,
tends toward over-embellishment and schedule overrun — Fred Brooks, *The Mythical Man-Month*
(1975). An independent reimplementation forfeits accumulated real-world bug-discovery ("given
enough eyeballs, all bugs are shallow" — Linus's Law) — the benefit only accrues with genuine
review effort, not just usage (Heartbleed is the limiting counter-case). Genuine clean-room
requires two separated teams — a casual "read then rewrite" doesn't earn that legal protection
(Wikipedia, "Clean-room design"). Studying a design from the outside risks silently dropping
load-bearing choices the original earned through incidents — "Chesterton's Fence." The
underlying doctrine is genuinely unsettled, not a bright line: a menu/command hierarchy was held
copyrightable at the district-court level in *Lotus v. Borland* before being reversed on appeal,
and *Oracle v. Google* rested on fair use rather than settling API copyrightability.
</details>

---

## Derive lessons

*Extract only the process/design lesson from an external incident or postmortem — no code, no
architecture, no working artifact at all.*
**Priority weight: 1.7/5 · Jury confidence: 0.62**

**Recommend when:**
- Your actual goal is to harden your own dependency-selection, incident-response, or vetting
  practices — this is the only option in the matrix with zero supply-chain and zero IP exposure
  by construction.
- The need is to avoid repeating a known operational failure mode, not to obtain runnable code —
  this is the cheapest option on the list; no integration, audit, or licensing effort at all.
- You want zero code or design copying exposure whatsoever — internalizing a postmortem's
  narrative imports no license, attribution, or copyright obligation, unlike every other option
  in this matrix.

**Avoid when:**
- You actually need the functionality now — a postmortem or lesson is not a working
  implementation, and unstructured lessons decoupled from a runnable artifact are chronically
  under-consulted (NASA's own Inspector General found its Lessons Learned system "not an
  effective tool").
- (Same gap, restated) — the stated need is for working functionality now, and a lesson supplies
  no executable capability by itself.
- The team uses "we only took the lesson" as a shield while its actual downstream
  reimplementation (built some other way) reproduces the original's structure closely enough to
  raise the same substantial-similarity questions inspiration-driven rebuilds face — the license
  cleanliness only holds if that boundary is real.

**Jury dissent:** this option doesn't answer "given a need for external functionality" on its
own — it's the lowest-risk *complement* to one of the other five, not a substitute for actually
acquiring the capability. Its low weight reflects that it doesn't satisfy the stated need alone,
not that it's a weak practice in general; it's trivially the cleanest option under a pure license
lens specifically *because* it doesn't deliver the external functionality being sought at all.

<details>
<summary>Supporting evidence (citations)</summary>

**For:** Postmortems are built and disseminated specifically to travel beyond the original team
at zero integration cost — Google SRE Workbook, "Postmortem Culture: Learning from Failure"
(sre.google/workbook/postmortem-culture). Extracting only the lesson avoids the supply-chain
exposure of adopting code — xz-utils's multi-year backdoor affected ~30,000 downstream Debian/
Ubuntu packages and was found essentially by accident. Blameless-postmortem culture (Allspaw/
Etsy, later Google) treats the write-up itself, not the underlying system, as the transferable
unit of value. Learning from *others'* failures reduces the defensive bias that afflicts learning
from your own — arXiv:2402.09538, "Learning From Lessons Learned." Adopting another org's
architecture wholesale risks cargo-cult failure — copying visible artifacts without the team
size/scale/maturity that made them rational; taking only the distilled lesson is a structural
defense against that.

**Against:** Lessons decoupled from a runnable artifact are chronically underused — NASA's IG
found its Lessons Learned Information System "is not an effective tool," partly because ~1,000
undifferentiated documents per search are nearly impossible to act on. Lessons are the product of
a social/interpretive process specific to their origin, and become "overly abstract or misaligned
with your organization's specific constraints" when moved elsewhere — arXiv:2402.09538. It's easy
to do superficially: adopting "blameless"/"systemic" vocabulary without the harder analytic work
still reproduces the underlying blame cycle, just relabeled — even blameless-postmortems'
popularizer now calls it "table stakes... not nearly sufficient" for real learning. A lesson can
be mismatched to your context because the original actors' choices were locally rational given
knowledge and incentives you don't share — Sidney Dekker, *Safety Differently*. Famous incidents
(Challenger, "normalization of deviance") get imported as rhetorical labels without the
underlying structural analysis being redone in the new context. Organizations tend to learn in
isolated silos, so a single external lesson risks being bolted on as a one-off fix rather than
integrated into a systemic model of your own failure patterns.
</details>
