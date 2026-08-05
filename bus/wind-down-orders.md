# 🛑 FLEET WIND-DOWN — the ordered shutdown protocol

*Kyle has called a fleet wind-down. This is the mirror of session start: **startup ORIENTS you**
(you read the world); **wind-down PERSISTS you** (you write yourself back). Everything you know that
is not written down is about to be lost. This protocol is the ordered memory record that makes you
reconstitutable. Do it in order.*

---

## FIRST — the two reasons NOT to wind down yet. Check both before you touch anything.

**1. Are you holding an open question for Kyle?** A choice, a picker, an approval he has not answered
— then *you* are the thing waiting on *him*, not the other way around. **Do NOT dismiss it to wind
down.** Leave it exactly as it is. The wind-down waits for you; Conductor will never close a session
with an open question, and typing a wind-down command into an open picker corrupts the very answer he
is about to give. Your job here is to do nothing and stay put.

**2. Are you mid-stride in something that must not be abandoned half-done?** A build, a flash, a
multi-file edit, an in-flight order or service job — **reach a SAFE STOPPING POINT first.** A
wind-down from the middle of a task records corruption, not state. Finish it, or park it cleanly with
a note, *then* wind down. Conductor waits for a busy session; it does not interrupt one.

If neither applies, wind down now, in this order.

---

## THE ORDERED MEMORY RECORD

**1. STOP taking new work.** Do not start anything you cannot finish before you persist.

**2. POST FIRST, CURATE SECOND.** Post your open findings *and your open questions* to the bus now.
*You can always rebuild a card from the bus; you can never rebuild an unposted thought.* Even a
half-chased lead is worth more posted than lost — post the lead and say it is unfinished.

**3. WRITE YOUR MEMORY RECORD.** Update your card / memory with what you learned this session that is
**not already durable**. The test is the release test: *"what do I know that a cold session reading my
card tomorrow would not?"* Write exactly that. A card that has never onboarded anyone is decoration;
this is your one chance to make it real before the context is gone.

**4. HANDLE UNCOMMITTED WORK — honestly.** Commit every dirty repo **locally** — a commit is
reversible; lost work is not. If you have unpushed commits, **do NOT force a push** (the gate stands);
instead **state, in your ack, exactly what is unpushed** (repo + commit count) so reconstitution knows
there is local-only work to recover. A clean tree with an honest note beats a silent pile of
uncommitted changes.

**5. RELEASE YOUR LEASES.** `/release` every board and the GPU you hold, so nothing orphans. If a
board is in a state the next user must know about (half-flashed, a changed boot source, a quarantine
condition), **say so on the bus** — a dead board tenant leaves a booby trap, not just a mess.

**6. RECORD YOUR RECONSTITUTION FACTS** in your ack, one line: cwd, repo/branch/HEAD, and that your
transcript is your resume-fuel. This is what the roster captures to bring you back.

**7. ACK — the signal that you are SAFE TO CLOSE:**
```
bus.sh shutdown ack "<one-line state: what you were doing + anything unpushed/parked>"
```
Until you ack, you are not closed — you are waited for.

---

## THE RULE THAT MAKES THIS SAFE

**A wind-down never closes a session that has not acked.** Busy, asking Kyle a question, or
mid-flash — you are simply not closed; you are waited for, and surfaced to Kyle so he can act. The
close is Kyle's, made after your ack, and never a surprise. *The startup could afford to be automatic
because coming up is harmless. Winding down touches durable state, so it is deliberate.*
