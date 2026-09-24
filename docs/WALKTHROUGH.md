# Walkthrough: how lakehouse-mcp works

Read alongside the code. Six modules, and one of them is the whole point.

---

## `safety.py` is the product

Everything else is convenience. If this module is wrong, the project is a liability
rather than a tool, because the caller is an agent that will cheerfully try things.

### Why the parser, not a regex

The obvious implementation is "reject the query if it contains DROP, DELETE,
INSERT...". That loses immediately:

- `CREATE TABLE evil AS SELECT * FROM silver` contains SELECT and is a write.
- `SELECT 1; -- harmless\nDELETE FROM silver` hides the second statement behind a
  comment.
- A string literal can contain any keyword you care to blocklist.

`duckdb.extract_statements()` parses without executing and reports what each
statement actually is. That is the only version of this check that does not
eventually lose to a clever input.

### The PRAGMA hole, and why it needed a second control

DuckDB classifies `PRAGMA database_list` as a **SELECT**. The type check passes it.
It cannot reach lakehouse data and cannot read files, so the blast radius is small,
but a tool advertising "read-only SELECT" should not silently also mean "and
enumerate the server internals". So there is an explicit prefix check for
`PRAGMA`, `CALL`, `DESCRIBE` and `SHOW`, applied after stripping leading comments
and whitespace so a comment cannot smuggle one past.

This is worth knowing because it is the kind of thing a reviewer finds: the
principled control (ask the parser) had a gap, and the gap needed a second,
less elegant control rather than a hand-wave.

### The three-line lockdown, and why the order matters

```python
con.execute("SET enable_external_access = false")
con.execute("SET disabled_filesystems = 'LocalFileSystem'")
con.execute("SET lock_configuration = true")
```

The lock goes last because it freezes every setting including the two above it.
Get the order wrong and the lock succeeds while the protections it was supposed to
preserve were never applied.

Tables reach DuckDB as Arrow datasets, not file paths, so PyArrow does the file
reading on the Python side. That is why disabling DuckDB's filesystem does not
break queries, and there is a test asserting exactly that, so nobody later
"fixes" the hardening because they assumed it must be breaking something.

---

## `config.py`: allowlisted roots

```python
target = Path(candidate).expanduser().resolve()
```

**Resolve, then check.** `resolve()` collapses `..` and follows symlinks, so a path
that looks contained cannot escape through either. Checking the string first and
resolving later is the classic traversal bug, and there are tests for both the
`../../..` form and the symlink form.

The row caps exist because an agent will ask for a billion rows without meaning
anything by it. `clamp_rows` bounds what a caller can request; the query wrapper
applies it whether or not the caller wrote a LIMIT.

---

## `tables.py`: reading the Delta log directly

No Spark, no JVM. A Delta table is a directory with a `_delta_log/` in it, and
delta-rs reads that log as the filesystem operation it is.

`find_tables` stops descending once it finds a table. The data files underneath are
not more tables, and walking into them on a real lakehouse is the difference
between instant and minutes.

`type_name()` exists because `str()` on a delta-rs primitive gives
`PrimitiveType("long")`. An agent about to write a CAST reads that and guesses
wrong, so the schema tool hands back `long`.

`table_history` is the tool that earns the project its keep: Delta commits carry
operation metrics including row counts, so "why did last night's load drop 12% of
rows?" is usually answerable from the log without touching the data.

---

## `query.py`: one SELECT, every table registered

Every discoverable table is registered under its directory name before the query
runs, which is what makes joins across layers possible. That is the difference
between a useful tool and a table viewer.

The row cap is applied by **wrapping** the caller's SQL:

```python
f"SELECT * FROM ({sql}) AS _q LIMIT {row_limit + 1}"
```

`+ 1` so the server can tell the difference between "there were exactly this many
rows" and "there were more and I cut them". An agent handed a silently truncated
result will reason about it as though it were complete, which is worse than an
error.

Time travel is `table` plus `version`: the same query, against that table as it was
at that Delta version.

---

## What it looks like against a real lakehouse

Pointed at the Streamhouse warehouse:

```
list_tables  -> bronze, bronze_dlq, dq_results, gold_daily_account_totals,
                quarantine, silver
history      -> v0 WRITE rows=590
query        -> acc_0090 INR 3,304,430   (top account by volume)
dq_results   -> non_positive_amount  failed=62  rate=0.0208  passed=False
                unknown_currency     failed=66  rate=0.0221  passed=False
refused      -> DROP TABLE silver            only SELECT is permitted, got DROP
                PRAGMA database_list         introspection not permitted
                SELECT 1; DELETE FROM silver expected one statement, got 2
                COPY silver TO '/tmp/leak'   only SELECT is permitted, got COPY
```
