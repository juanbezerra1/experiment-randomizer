# Design notes

Exact definitions, for anyone who wants to re-implement the check or audit a log by hand.

## 1. Streams

`Stream(seed, *path)` seeds Python's Mersenne Twister with
`int.from_bytes(sha256(json.dumps([seed, *path], separators=(",", ":"))).digest(), "big")`.
Only `Random.random()` is used (the standard library guarantees its output for a given seed;
`shuffle`, `randrange` and `choice` carry no such guarantee). Two derived operations:

* `below(n) = min(int(random() * n), n - 1)`, a uniform integer in `[0, n)` with a bias under
  `n / 2**53`;
* `shuffle(items)`, Fisher-Yates from the end: for `i = len-1 .. 1`, swap `items[i]` with
  `items[below(i + 1)]`.

Different parts of a study use different paths of the same master seed, so changing one never
moves another: `("arms",)` for the arm sequence and `("orders", session)` for the condition orders
of one session.

## 2. The protocol

`study.json` holds `format`, `arms`, `arm_weights`, `arm_block_sizes`, `conditions`, `n_rounds`,
`design` and `seed`. Labels match `[A-Za-z0-9][A-Za-z0-9_.+]*`: no spaces, `-`, `;` or quotes, so
a round written as `c2-c4-c1-c3` is unambiguous, and nothing can start with `=`, `+` or `-` and be
read as a formula by a spreadsheet. The **protocol hash** is the SHA-256 of the canonical JSON
(sorted keys, no spaces), so reformatting the file does not change it and changing any value does.

## 3. Arms: permuted blocks

With weights `w` (sum `W`) and block sizes `S` (each a multiple of `W`): draw a size from `S`
(`below(len(S))`), put `size * w_i / W` copies of arm `i` in a list, shuffle it, append it to the
sequence, and repeat until the sequence is long enough. The arm of session `k` is element `k` of
the sequence, which is always a prefix of the longer sequences: asking for session 5 or session 50
gives the same first five arms. Defaults: weights all 1, sizes `(2W, 3W)`.

In a block of size `s` with equal arms the difference between any two arms is at most `s / 2` at
every moment, so with blocks of 4 and 6 it never exceeds 3, and at the end of a study of even size
never exceeds 2.

## 4. Conditions: one order per round

`shuffle`: each round is an independent shuffle of the conditions.

`latin`: the rows of the cyclic Latin square, row `i` being `i, i+1, ..., i+n-1 (mod n)`.

`williams`: first row `0, 1, n-1, 2, n-2, ...` (for `n = 4`: `0 1 3 2`); the other rows are its
cyclic shifts. For even `n` the successive differences of the first row are all distinct modulo
`n`, so every ordered pair of conditions is adjacent exactly once across the `n` rows (balanced
first-order carry-over). For odd `n` the reversed rows are added, `2n` rows, each ordered pair
adjacent exactly twice.

For `latin` and `williams`, a session draws a random relabelling of the conditions and a random
starting row, and uses consecutive rows (wrapping around) for consecutive rounds. Because the rows
are cyclic shifts of each other, the starting row is redundant with the relabelling for the cyclic
designs (it only matters for the reversed rows of an odd Williams design), and a session is
determined by the relabelling alone: at most `n!` distinct session patterns.

## 5. The log

CSV, `;` separator, UTF-8 with a byte-order mark, CRLF line ends. Columns:

```
kind;session;timestamp;arm;round_1;...;round_n;note;hash
```

`kind` is `draw` or `note`; a note row repeats the number of the session it is about, with empty
`arm` and rounds. `timestamp` is local time with its UTC offset, to the second.

```
fields(row) = [kind, session, timestamp, arm, round_1, ..., round_n, note]      (all strings)
hash(row)   = SHA-256( previous_hash + "\n" + json(fields(row), separators=(",", ":"),
                                                   ensure_ascii=False) )
previous_hash = protocol hash                 for the first row
              = hash of the row before        otherwise
```

To audit a log without this program, recompute those hashes with any SHA-256 and JSON library.

## 6. What `verify` checks

For every row, in order:

1. its stored hash equals the recomputed one (this alone catches an edit, a deletion, an insertion,
   a duplication or a reordering, at the first affected line);
2. `kind` is `draw` or `note`;
3. for `draw` rows, the session number is the previous one plus one;
4. for `draw` rows, the arm and every round equal what `draw(protocol, session)` returns (this
   catches a forger who recomputed the hashes);
5. for `note` rows, the session is one that has already been drawn.

Optionally `--expect-head` compares the final hash with one written down earlier. Regeneration is
linear in the length of the log: the arm sequence is built once, and the orders of each session
are independent of the others.

## 7. Writing

`Study.next()` and `Study.annotate()` take an exclusive lock on `.lock` (`flock` on POSIX,
`msvcrt.locking` on Windows: the operating system releases it if the process dies), read and verify
the whole log, build the next row, append it with a single `write`, flush and `fsync`, and release
the lock. A crash can therefore leave a session that was logged but never looked at; it cannot
leave one that was looked at but not logged.

The lock is only as good as the file system under it, and a sync client can copy or duplicate the
log behind the program's back. `exprand.placement` therefore looks at where the folder is, and the
commands that write (`init`, `next`, `annotate`, `gui`) print a warning when it is a Windows UNC
path or a drive that Windows reports as remote, a folder on an NFS, SMB/CIFS, sshfs or similar mount
(the file system of the mount that holds the folder, from `/proc/self/mountinfo` or `mount`), or a
folder of OneDrive, Dropbox, Google Drive or iCloud Drive (by the name of a path component, and the
`OneDrive` environment variables on Windows). A link is followed first. It is advice only: nothing
refuses to draw, the output of the other commands is untouched, the warning goes to stderr so that
`--json` stays valid, and `EXPRAND_NO_LOCATION_WARNING=1` silences it. "No warning" means "not
recognised", not "safe": other sync tools, and a sync client set up on a folder with an ordinary
name, are not seen.

## 8. Not covered

Allocation concealment, stratification, minimisation, and multi-site use. The log detects edits;
it does not stop them, and it is not a signature scheme (there is no secret key).
