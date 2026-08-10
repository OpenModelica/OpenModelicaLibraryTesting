# The OpenModelicaLibraryTesting result database

This document describes how the library testing results are stored: the current
sqlite3 layout, what every table and column means, how the scripts query it, and
the PostgreSQL layout the data is being migrated to (issue
[#295](https://github.com/OpenModelica/OpenModelicaLibraryTesting/issues/295)).

## Where the databases live

Each test machine keeps a single sqlite3 file called `sqlite3.db` in the working
directory of the test run. The files are published at:

| machine | URL | on omod-r630-2 | size | tables | rows |
| --- | --- | --- | --- | --- | --- |
| ripper1 | <https://libraries.openmodelica.org/sqlite3/ripper1/sqlite3.db> | `/var/www/libraries.openmodelica.org/sqlite3/ripper1/sqlite3.db` | 11.8 GB | 34 | ~69 million |
| ripper2 | <https://libraries.openmodelica.org/sqlite3/ripper2/sqlite3.db> | `/var/www/libraries.openmodelica.org/sqlite3/ripper2/sqlite3.db` | 15.5 GB | 54 | ~91 million |

(sizes as of 2026-08-10; both are at `PRAGMA user_version` 3)

Every branch/configuration tested on a machine ends up in that machine's file,
which is why the files are large and why two machines cannot test the same job
without overwriting each other's results. The tables are the branches currently
tested (`master`, `newInst-newBackend`, `cpp`, `master-fmi`, `gbode`, `cvode`,
`ida`, `daemode`, ...) plus one per historical release (`v1.9` ... `v1.27`,
`v1.11-fmi` ...). `master` alone holds ~43 million rows on ripper1.

Six table names exist on both machines - `master`, `newInst`, `heavy_tests`,
`v1.17`, `libversion` and `omcversion` - so a shared database mixes rows from
both. They are distinguished by their `date`, which is unique per run and
machine.

The scripts always open the file by the hardcoded relative name `sqlite3.db`:
`test.py` writes it, `report.py`, `all-reports.py`, `all-plots.py`,
`single-model.py`, `clean-dates.py` and `clean-empty-omcversion-dates.py` read
it.

## Schema version

`test.py` keeps the layout version in sqlite's `PRAGMA user_version` and
migrates on startup (`test.py`, around the `CREATE TABLE` block):

| user_version | meaning |
| --- | --- |
| 0 | empty/new database; `omcversion` and `libversion` are created |
| 1 | `libversion.confighash` added |
| 2 | `parsing` added to every per-branch table |
| 3 | current layout |

A database with a higher `user_version` makes `test.py` exit rather than guess.

## Tables

### Per-branch result tables

There is **one table per tested branch/configuration**, named after the branch
(`master`, `gbode`, `ida`, `cvode`, `master-fmi`, `newInst-newBackend`,
`heavy_tests`, ...), created on demand by `test.py`:

```sql
CREATE TABLE if not exists [<branch>] (
  date        integer NOT NULL,  -- unix epoch: start of the test run
  libname     text    NOT NULL,  -- library incl. version suffix, e.g. Buildings_9.1.0
  model       text    NOT NULL,  -- full Modelica class name of the tested model
  exectime    real    NOT NULL,  -- wall clock for the whole test of this model [s]
  frontend    real    NOT NULL,  -- time in the front end [s]
  backend     real    NOT NULL,  -- time in the back end [s]
  simcode     real    NOT NULL,  -- time generating SimCode [s]
  templates   real    NOT NULL,  -- time running the code generation templates [s]
  compile     real    NOT NULL,  -- time compiling the generated code (or building the FMU) [s]
  simulate    real    NOT NULL,  -- time simulating [s]
  verify      real    NOT NULL,  -- time spent in diffSimulationResults [s]
  verifyfail  integer NOT NULL,  -- number of variables that differ from the reference
  verifytotal integer NOT NULL,  -- number of variables compared against the reference
  finalphase  integer NOT NULL,  -- how far the model got, see below
  parsing     real    NOT NULL   -- time loading/parsing the library [s]
)
```

Notes on the values, which are produced by `testmodel.py` and written by
`test.py`:

- `date` is `int(time.time())` taken **once per test run** (`testRunStartTimeAsEpoch`),
  so all rows of one run share the same date. It is the join key to
  `omcversion`/`libversion` and the x-axis of every history plot.
- The phase times are exclusive, computed by subtracting the nested OMC timers
  from each other (`frontend = frontend - backend`, `backend = backend - simcode`, ...).
  A phase that was never reached is stored as `0.0`.
- `compile` is the `build` measurement: `make -f <model>.makefile` for the C
  runtime, the FMU build for FMI configurations, and the JIT compile time for
  wasm-jit.
- `exectime` is the total wall clock of the model's test process. `test.py`
  reads back the most recent value (`SELECT exectime ... ORDER BY date DESC LIMIT 1`)
  to sort the queue longest-job-first.
- `verifyfail`/`verifytotal` are `len(diff.vars)` and `diff.numCompared`; a model
  without reference variables stores `0`/`0` and still reaches phase 7.

`finalphase` is the last phase completed; `shared.finalphaseName` maps it to:

| value | name | meaning |
| --- | --- | --- |
| 0 | Failed | the front end did not finish |
| 1 | FrontEnd | front end ok, back end failed |
| 2 | BackEnd | back end ok, SimCode failed |
| 3 | SimCode | SimCode ok, templates/translation failed |
| 4 | Templates | translated, but compilation/build failed |
| 5 | Compile | built, but the simulation failed |
| 6 | Simulate | simulated, but the result does not verify (or was not compared) |
| 7 | Verify | the result matches the reference file |

Reports count models per phase with `WHERE finalphase >= i`, so the columns of
the HTML tables are cumulative.

### `omcversion`

Maps a test run to the compiler that produced it:

```sql
CREATE TABLE if not exists [omcversion] (
  date       integer NOT NULL,  -- same epoch as the result rows of that run
  branch     text    NOT NULL,  -- branch/configuration name = result table name
  omcversion text    NOT NULL   -- output of getVersion(), e.g. "OMCompiler v1.26.0-dev.42+g0123abc"
)
```

One row per run. `report.py` and `all-reports.py` use it to label a run, and
`all-reports.py` walks it in date order to pair consecutive runs when generating
the regression reports.

### `libversion`

Maps a test run to the library versions and configuration used:

```sql
CREATE TABLE if not exists [libversion] (
  date       integer NOT NULL,  -- same epoch as the result rows of that run
  branch     text    NOT NULL,
  libname    text    NOT NULL,  -- as in the result table
  libversion text    NOT NULL,  -- conf["libraryLastChange"]: version + git revision/zip hash
  confighash integer NOT NULL   -- hash of the configuration and the reference files
)
```

One row per (run, library). `confighash` is `strToHashInt()` over the
configuration dictionary plus the hashes of all reference files, so any change
to the config or to a reference file yields a different value.

This drives the "do we need to test this at all" decision in `test.py`: before
testing a library it looks for

```sql
SELECT date,libversion,libname,branch,omcversion FROM [libversion] NATURAL JOIN [omcversion]
WHERE libversion=? AND libname=? AND branch=? AND omcversion=? AND confighash=? ORDER BY date DESC LIMIT 1
```

and skips the library when the exact same combination of library version, OMC
version and configuration was already tested.

### `datelookup_<branch>` (obsolete)

`datelookup_<branch>(date, runDate, libname, branch)` was a cache mapping every
omcversion date to the latest run date of a library. The code that fills it in
`all-plots.py` sits inside a triple-quoted block and is no longer executed;
neither ripper1 nor ripper2 still has such a table. The migration skips them.

### Indexes

No index is stored permanently. `test.py` drops `idx_<branch>_date`,
`idx_omcversion_date` and `idx_libversion_date` on startup (they slow the bulk
insert down), and `report.py`/`all-reports.py`/`all-plots.py` recreate
`idx_<branch>_date` when they need it.

## How a test run writes the database

1. Open `sqlite3.db`, apply the `user_version` migration, `CREATE TABLE IF NOT EXISTS [<branch>]`.
2. Compute `confighash` per library, skip libraries already covered (query above).
3. Run the tests; each model writes `files/<name>.stat.json`.
4. At the end, in one transaction: one `INSERT` per model into `[<branch>]`, one
   `INSERT` per library into `[libversion]`, one `INSERT` into `[omcversion]`,
   then `conn.commit()`.

Nothing is written while the tests run, so an aborted run leaves no rows behind,
and two machines running the same job produce two full sets of rows in two
separate files - whichever file is copied back last wins.

## Housekeeping scripts

- `clean-dates.py --start --stop`: `DELETE FROM [<tbl>] WHERE date<? AND date>?`
  over every table, then `VACUUM`. Removes a range of bad runs.
- `clean-empty-omcversion-dates.py`: drops `omcversion` rows whose date has no
  result rows in the corresponding branch table.

## PostgreSQL layout

The PostgreSQL database is a **mirror** of the sqlite3 one: the same tables with
the same names and columns, one table per branch plus `omcversion` and
`libversion`. That way the test scripts can push new results to the network
database with the same statements they use today, and the report scripts need no
query rewriting beyond the sqlite `[name]` / PostgreSQL `"name"` quoting.

Only the types are adapted:

| sqlite3 | PostgreSQL |
| --- | --- |
| `integer` | `bigint` (`integer` for `verifyfail`, `verifytotal`, `finalphase`) |
| `real` | `double precision` |
| `text` | `text` |
| `NOT NULL` on every column | only on the key columns, see below |
| `PRAGMA user_version` | not used; the `parsing` column always exists |
| `datelookup_*` | not migrated (derived data, no longer generated) |

### Keys

Each table gets a unique key, which sqlite3 never had:

| table | key |
| --- | --- |
| `<branch>` | `(date, libname, model)` - a run tests every model of a library once |
| `omcversion` | `(date, branch)` - one row per run |
| `libversion` | `(date, branch, libname, confighash)` - one row per run and library |

This is what makes a shared database possible: results from a second test
machine can be merged into a table that already holds another machine's rows,
and a run that is pushed twice cannot produce duplicates.

Only those key columns are `NOT NULL`. The sqlite3 tables declare every column
`NOT NULL`, but `CREATE TABLE if not exists` means tables created by an older
`test.py` keep their old, laxer declaration, so the historical data does not
necessarily hold up. `libversion.libversion` for instance stores empty strings
for some old runs.

So a branch table becomes:

```sql
CREATE TABLE "master" (
  date        bigint NOT NULL,
  libname     text   NOT NULL,
  model       text   NOT NULL,
  exectime    double precision NOT NULL,
  frontend    double precision NOT NULL,
  backend     double precision NOT NULL,
  simcode     double precision NOT NULL,
  templates   double precision NOT NULL,
  compile     double precision NOT NULL,
  simulate    double precision NOT NULL,
  verify      double precision NOT NULL,
  verifyfail  integer NOT NULL,
  verifytotal integer NOT NULL,
  finalphase  integer NOT NULL,
  parsing     double precision NOT NULL
);
```

Two things to keep in mind when querying it:

- Identifiers must be **double quoted**, not bracketed: branch names such as
  `newInst-newBackend` contain upper case letters and dashes, which PostgreSQL
  would otherwise fold to lower case or reject.
- All test machines write into the same tables, so a run is identified by
  `date` (plus `branch`) exactly as before. Use `--pgschema ripper1` if a
  machine should be mirrored into a schema of its own instead.

Indexes are created by `sqlite2postgres.py --index` rather than on the fly:
`(date)` on every table, `(branch, date)` on `omcversion`,
`(branch, libname, date)` on `libversion` and `(libname, date)` on the branch
tables.

## Migrating

Run this **on omod-r630-2 (openmodelica.org)**: the sqlite3 files and the
PostgreSQL server are on the same machine, so the data never goes over the
network. Pushing it from a developer machine works too, but a home uplink does
0.3-1.8 MB/s, which means hours for ~27 GB.

```bash
export PGPASSFILE=~/.pgpass          # never put the password on the command line
DB=/var/www/libraries.openmodelica.org/sqlite3
./sqlite2postgres.py --host localhost --sqlite $DB/ripper1/sqlite3.db --source ripper1
./sqlite2postgres.py --host localhost --index
./sqlite2postgres.py --host localhost --sqlite $DB/ripper2/sqlite3.db --source ripper2 --skip-existing
./sqlite2postgres.py --host localhost --index
./sqlite2postgres.py --host localhost --sqlite $DB/ripper1/sqlite3.db --verify
```

The order matters. ripper1 goes in first and without an index, which is the
fast path. `--index` then creates the unique keys, so that ripper2, loaded with
`--skip-existing`, keeps whatever is already there whenever a key collides -
ripper1 wins. The second `--index` covers the tables that only exist on ripper2.

On the databases as of 2026-08-10 the priority never actually fires: not one
`(branch, date)` is shared between the two machines, not even for the four
branches both of them test, so the merge is a plain union. The rule matters for
re-runs and for two machines pushing results later on.

### Disk space

A branch table row measures **212 bytes** in PostgreSQL (measured on `v1.10`,
average `model` length 57, `libname` 17). The whole migration is therefore about

- 34 GB of table data for the ~160 million rows, plus
- 10-12 GB for the `(date)` and `(libname, date)` indexes.

so **plan for ~50 GB**. On omod-r630-2 the cluster lives in
`/var/lib/postgresql/16` on the root LV, which has 14 GB free, while the `data`
ZFS pool has 2.9 TB free. Put the database on the pool before loading, e.g.

```bash
sudo zfs create -o mountpoint=/data/postgres -o compression=lz4 -o recordsize=16k data/postgres
sudo install -d -o postgres -g postgres /data/postgres/omdb
sudo -u postgres psql -c "CREATE TABLESPACE omdb_ts LOCATION '/data/postgres/omdb'"
sudo -u postgres psql -c "ALTER DATABASE omdb SET TABLESPACE omdb_ts"   # needs no open connections
```

`lz4` on the dataset typically cuts this data to well under half, since the
model names repeat in every run.

### Catching up with the jobs that are still running

The migration is a snapshot: a test run that was started before it, or any run
that still writes its own sqlite3 file, adds rows the shared database has never
seen. `--catch-up` copies them over:

```bash
./sqlite2postgres.py --host localhost --sqlite $DB/ripper1/sqlite3.db --source ripper1 --catch-up
./sqlite2postgres.py --host localhost --sqlite $DB/ripper2/sqlite3.db --source ripper2 --catch-up
```

It reads the database from the start and keeps the runs the shared database
does not have, which takes two to three minutes per machine. Not "everything
past the rowid the migration stopped at", tempting as that is: `VACUUM`
renumbers the rowids of these tables and `clean-empty-omcversion-dates.py` runs
one after every test, so that number does not survive a test run. Picking the
runs by date is also what makes it correct for `master`, `newInst`,
`heavy_tests` and `v1.17`, where both machines write into the same table.

Repeating it costs nothing but the reading: the keys reject anything already
there. Run it once more right after the jobs are switched to the shared
database; from then on nothing writes the sqlite3 files any more and there is
nothing left to catch up with.

`--source` only names the machine for the bookkeeping table
`migration_progress(source, tbl, last_rowid, rows_read, done)`, which records how
far each sqlite table has been copied. Each batch is committed together with its
progress row, so an interrupted migration continues from the last rowid that
made it in and never copies a batch twice; the command can simply be run again.
Rows are streamed in batches of `--batch` (200000 by default) through
`COPY ... FROM STDIN`, so memory use does not depend on the size of the database.

`COPY` is used in its text format rather than CSV on purpose: an empty CSV field
reads back as NULL, which would silently turn the empty `libversion` strings in
the old data into NULLs.
