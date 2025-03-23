#!/usr/bin/env python3
# Jellyfin Migrator - Adjusts your Jellyfin database to run on a new system.
# Copyright (C) 2022  Max Zuidberg
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import datetime
import json
import os
import sqlite3
import xml.etree.ElementTree as ET

from pathlib import Path
from shutil import copy
from time import time
from functools import partial

from jellyfin_migrator.utils import get_dotnet_MD5
from jellyfin_migrator.utils import jf_date_str_to_python_ns
from jellyfin_migrator.utils import get_datestr_from_python_time_ns
from jellyfin_migrator.utils import nested_root_path_replacer
from jellyfin_migrator.utils import nested_id_path_replacer
from jellyfin_migrator.id_scanner import (
    bid2sid, sid2did, sid2bid, convert_ancestor_id
)

# Choose an appropriate config file (
# TODO: config should really be a path to some yaml or json)
# import jellyfin_migrator_config as config
# import jellyfin_migrator.windows_config as config
import jellyfin_migrator.linux_config as config


try:
    # For DEV, but should make these optional
    import rich
    import ubelt as ub
except ImportError:
    raise

LOG_FILE = config.LOG_FILE
PATH_REPLACEMENTS = config.PATH_REPLACEMENTS
FS_PATH_REPLACEMENTS = config.FS_PATH_REPLACEMENTS
ORIGINAL_ROOT = config.ORIGINAL_ROOT
TODO_LIST_PATHS = config.TODO_LIST_PATHS
TODO_LIST_ID_PATHS = config.TODO_LIST_ID_PATHS
TODO_LIST_IDS = config.TODO_LIST_IDS


# Since library.db will be needed throughout the process, its location is stored
# here once it's been moved and updated with the new paths.
LIBRARY_DB_STAGING_PATH = Path()
LIBRARY_DB_SOURCE_PATH = Path()


# Similarly, the IDs are used in "hard-to-reach" places and are thus global, too.
IDS = dict()


# Custom print function that prints to both the console as well as to a log file
LOGGING_NEWLINE = False


# from kwutil import util_logger  # NOQA
# logger = util_logger.Logger(__name__).configure(logfile=LOG_FILE)


def print_log(*args, **kwargs):
    global LOGGING_NEWLINE
    print(*args, **kwargs)

    # Each new line gets a timestamp. That requires tracking of (previous)
    # line endings though. This is not perfect, but perfectly fine for this
    # script.
    dt = ""
    if LOGGING_NEWLINE:
        dt = "[" + datetime.datetime.now().isoformat(sep=" ") + "] "
    if kwargs.get("end", "\n") == "\n":
        LOGGING_NEWLINE = True
    else:
        LOGGING_NEWLINE = False
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        print(dt, *args, **kwargs, file=f)


def update_db_table(
        file,
        replace_dict,
        replace_func,
        table,
        path_columns=(),
        json_columns=(),
        jf_image_columns=(),
):

    """
    repair(){
        cat <( sqlite3 "$1" .dump | grep "^ROLLBACK" -v ) <( echo "COMMIT;" ) | sqlite3 "fix_$1"
    }
    """
    # Initialize local variables
    rows_count, modified, ignored = 0, 0, 0

    # Initialize sqlite3 objects
    rich.print(f'[green]update_db_table, Connect to: file={file}')
    con = sqlite3.connect(file)
    cur = con.cursor()

    # If only one item has been specified, convert it to a list with one item instead.
    if not isinstance(path_columns, (tuple, set, list)):
        path_columns = [path_columns]
    if not isinstance(json_columns, (tuple, set, list)):
        json_columns = [json_columns]
    if not isinstance(jf_image_columns, (tuple, set, list)):
        jf_image_columns = [jf_image_columns]

    # This index will be used to separate the json from the path columns in the cur.execute
    # result further below.
    json_stop = len(json_columns)
    path_stop = json_stop + len(path_columns)

    # For the sql query the desired row names should be enclosed in ` ` and comma separated.
    # It's important to note that the json columns come first, followed by the path columns
    columns = ", ".join([f"`{e}`" for e in list(json_columns) + list(path_columns)] + list(jf_image_columns))
    # print(f'columns = {ub.urepr(columns, nl=1)}')

    # Query the unique IDs of all rows. Note: we cannot iterate over the rows using
    #     for row in cur.execute(get rows)
    # because the rows are modified by the loop, which breaks that iterator. Hence
    # the solution with reading all row ids and iterating over them instead.
    # Note: The cur.execute yields tuples with all the columns queried. Which means that
    # the array below actually contains _tuples_ with the id. This is however desirable
    # in our case; see below where id is used.
    todo = [rowid for rowid in cur.execute(f"SELECT `rowid` FROM `{table}`") if rowid[0]]
    rows_count = len(todo)
    t = time()
    for progress, id in enumerate(todo):
        # Print the progress every second. Note: this is the only usage of the "progress" variable.
        now = time()
        if now - t > 1:
            print_log(f"Progress: {progress} / {rows_count} rows")
            t = now

        # Query the columns we want to check/modify of the current row (selected by id).
        # Since the id is a binary object, it's not directly included in the f-string.
        # The cur.execute expects as second argument a _tuple_ with as many elements as
        # there are ? characters in the query string. This is the reason why we kept the
        # IDs as tuple. The only other place where this id is used is in the update query
        # at the end of the loop which requires - just like here - a tuple.
        row = [r for r in cur.execute(f"SELECT {columns} FROM `{table}` WHERE `rowid` = ?", id)]
        # This _should_ not occur, but I think I have seen it happen rarely. Safe is safe.
        if len(row) != 1:
            print_log(f"Error with rowid {id}! Resulted in {len(row)} rows instead of 1. Skipping.")
            continue
        # cur.execute returns a 2D tuple, containing all rows matching the query, and then
        # in each row the selected columns. We only selected a single row, hence row[0] is
        # all we care about (and all there is, see error handling above).
        # Secondly we want row to be modifiable, hence the conversion to a list.
        # list(row[0]) would btw return a list with 1 element: the tuple of the columns.
        row = [e for e in row[0]]

        # result has the structure {column_name: updated_data} which makes it very easy to build
        # the update query at the end.
        result = dict()

        # It's important to note that the tuple from cur.execute contains the columns _in the order
        # of the query string_. Therefore, we can separate json and path entries like this.
        jsons = row[:json_stop]
        paths = row[json_stop:path_stop]
        jf_imgs = row[path_stop:]
        for i, data in enumerate(jsons):
            if data:
                # There are numerous rows that have empty columns which would result in an error
                # from json.loads. Just skip them
                data = json.loads(data)
                data, mo, ig, wrns = replace_func(data, replace_dict)
                if wrns:
                    rich.print('[yellow]WARNING1')
                for warning in wrns:
                    print_log(warning)
                modified += mo
                ignored  += ig
                result[json_columns[i]] = json.dumps(data)
        for i, path in enumerate(paths):
            # One could also skip the empty objects here, but recursive_path_replacer handles them
            # just fine (leaves them untouched).
            path, mo, ig, wrns = replace_func(path, replace_dict)
            if wrns:
                rich.print('[yellow]WARNING2')
            for warning in wrns:
                print_log(warning)
            modified += mo
            ignored  += ig
            result[path_columns[i]] = path
        for i, imgs in enumerate(jf_imgs):
            # Jellyfin Image Metadata. Some DB entries look like this:
            #     %MetadataPath%\library\71\71d037e6e74015a5a6231ce1b7912acf\poster.jpg*637693022742223153*Primary*198*198*eJC5#hK#Dj9GR/V@j]xuX8NG0x+xgN%MxaX7spNGnitQ$kK0wyV@Rj # noqa
            # Yeah. That's a path and some other data within the same string, separated by *. More specifically:
            #     path * last modified date * image type * width * height * blur hash
            # where width, height, blur hash are apparently optional.
            # In theory, the * could occur as normal character within regular paths but it's unlikely.
            # Oh, and did I mention that such strings can contain multiple of these structures separated by a | ?
            # Source (Jellyfin Server 10.7.7): DeserializeImages, AppendItemImageInfo:
            # https://github.com/jellyfin/jellyfin/blob/045761605531f98c55f379ac9eb5b5b6004ef670/Emby.Server.Implementations/Data/SqliteItemRepository.cs#L1118 # noqa
            if not imgs:
                continue
            imgs = imgs.split("|")
            for j, img_properties in enumerate(imgs):
                if not img_properties:
                    continue
                img_properties = img_properties.split("*")
                # path = first property
                img_properties[0], mo, ig, wnrs = replace_func(img_properties[0], replace_dict)
                if wrns:
                    rich.print('[yellow]WARNING3')
                for warning in wrns:
                    print_log(warning)
                imgs[j] = "*".join(img_properties)
                modified += mo
                ignored  += ig
            imgs = "|".join(imgs)
            result[jf_image_columns[i]] = imgs

        # Similar to the initial query we construct a comma separated list of the columns, only this
        # time we write
        #     `columnname` = ?
        # While the new values are all strings, the question mark avoids any issues with handling
        # backslashes etc. The library offers an easy, built-in way to do it so there's no reason
        # to mess with it myself.
        # Note that this relies on result.keys() and result.values() returning the entries in the
        # same order (which is guaranteed).
        # Note: it can happen that no changes are made at all. In this case we can abort here and
        #       go for the next job from the todo_list.
        if not result:
            continue
        keys = ", ".join([f"`{k}` = ?" for k in result.keys()])
        query = f"UPDATE `{table}` SET {keys} WHERE `rowid` = ?"

        # The query has a question mark for each updated column plus one for the id to identify
        # the correct row.
        args = tuple(result.values()) + id
        try:
            cur.execute(query, args)
        except Exception as e:
            # This was mainly for debugging purposes and shouldn't be reached anymore. Doesn't
            # hurt to have it though.
            print('!!!!')
            print_log("Error:", e)
            print_log("Query:", query)
            print_log("Args: ", args)
            print_log(e)
            raise
            exit()
        else:
            if cur.rowcount < 1:
                # This was mainly for debugging purposes and shouldn't be reached anymore.
                # Doesn't hurt to have it though.
                print('!!!!')
                print_log("No data modified!")
                print_log("Query:", query)
                print_log("Args: ", args)
                raise
                exit()
    print_log(f"update_db_table, Processed {rows_count} rows in table {table}. ")
    print_log(f"update_db_table, {modified} paths have been modified.")

    # Write the updated database back to the file.
    con.commit()
    con.close()


def update_xml(file: Path, replace_dict: dict, replace_func) -> None:
    """
    Walks through an XML file and checks *all* entries.
    WARNING: The documentation of this parser explicitly mentions that it's not hardened against
    known XML vulnerabilities. It is NOT suitable for unknown/unsafe XML files. Shouldn't be an
    issue here though.
    """
    modified, ignored = 0, 0
    tree = ET.parse(file)
    root = tree.getroot()
    for el in root.iter():
        # Exclude a few tags known to contain no paths.
        # biography, outline: These often contain lots of text (= slow to process) and generate
        # false-positives for the missed path detection (see nested_root_path_replacer)
        if el.tag in ("biography", "outline"):
            continue
        el.text, mo, ig, wrns = replace_func(el.text, replace_dict)
        if wrns:
            rich.print('[yellow]WARNING(update_xml)')
        for warning in wrns:
            print_log(warning)
        modified += mo
        ignored  += ig
    print_log(f"Processed {ignored + modified} elements. {modified} paths have been modified.")
    tree.write(file)  # , encoding="utf-8")


def resolve_target(
        source: Path,
        target: Path,
        original_root,
        source_root,
        staging_root,
        target_root,
        replacements: dict,
        no_log: bool = False,
) -> Path:
    """
    Resolve the source path to the appropriate target path.
    """
    source = Path(source)
    target = Path(target)

    skip_copy = False

    # "auto" means the target path is generated by the same path replacement dictionary that's
    # also used to update all the path strings.
    # In this case we don't care about the stats returned by recursive_path_replacer, hence
    # the variable names.
    if len(target.parts) == 1 and target.name.startswith("auto"):
        if target.name == "auto-existing":
            skip_copy = True

        relpath = source.relative_to(source_root)
        original_source = original_root / relpath
        original = original_source
        staging = staging_root / relpath
        # target_v1, idgaf1, idgaf2, wrns1 = nested_root_path_replacer(original_source, to_replace=replacements)
        # target_v2, idgaf1, idgaf2, wrns2 = nested_root_path_replacer(target_v1, to_replace=FS_PATH_REPLACEMENTS)
        # for warning in wrns1 + wrns2:
        # for warning in wrns1:
        #     print_log(warning)
        # target_v2 = Path(target_v1)
        # target_v2 = Path(target_v2)
        # target = target_v2
        # print(f'!!!target={target}')
        # if not target.is_absolute():
        # if target.is_relative_to("/"):
        # assert target.is_relative_to("/")
        # # Otherwise the line below will make target relative to the _root_ of target_root
        # # instead of relative to target_root.
        # target = target.relative_to("/")
        target = target_root / relpath

        if 0:
            print('Resolving Target')
            # Maybe add an explicit "original source" which is equal to source if
            # running on an existing instance, but if you take the drive out and
            # need to run the migration, then there is a path the original jellyfin
            # referenecs, and there is the one that needs to be copied and then
            # modified.
            print(f'original = {original}')
            print(f'source   = {source}')
            print(f'staging  = {staging}')
            print(f'target   = {target}')
    else:
        raise AssertionError('not handled')

    # If source and target are the same there are two possibilities:
    #     1. The user actually wants to work on the given source files; maybe he already created
    #        a copy and directly pointed this script towards that copy.
    #     2. The user forgot that they shouldn't touch the original files.
    #     3. Something's wrong with the path replacement dict.
    # We are just going to error.
    if source == target:
        raise Exception("Target directory needs to be different than source")
    elif not skip_copy:
        # DELAY COPY
        ...
        # if not target.parent.exists():
        #     target.parent.mkdir(parents=True)
        # if not no_log:
        #     print_log(f"Copy... {source} -> {target}", end=" ")

        # copy(source, target)
        # if not no_log:
        #     print_log("Done.")
    return original, source, staging, target, skip_copy


def collect_files_to_process(lst: list, process_func, replace_func, path_replacements, use_extra_kwargs):
    """
    Processes the todo_list.
    It handles potential wildcards in the file paths and keeps track
    which files have already been processed. This allows you to have an
    automatic, wildcard copy in your todo_list that just copies the files
    to the (modified) destinations without processing them and without
    modifying those that have already been copied _and_ modified.
    Obviously this requires you to have the files that need processing
    first in the todo_list and only then the wildcard copies.

    lst: job list
    process_func: function to apply to jobs of lst.
    replace_func: function used by process_func to do the replacing of paths, ...

    NEW:
        Just returns the tasks that need to be executed. Won't execute them yet.
    """
    print('Calling collect_files_to_process')
    done = set()
    staged_tasks = []
    for job_idx, job in enumerate(lst):
        if "no_log" not in job:
            job["no_log"] = False
        source = job["source"]
        source_root = job['source_root']

        expanded_jobs = []
        if "*" in str(source):
            # Path has wildcards, process all matching files.
            #
            # Ironically Path.glob can't handle Path objects, hence the need
            # to convert them to a string...
            # It is expected that all these paths are relative to source_root.
            rel_source = source.relative_to(source_root)
            new_jobs = []
            for src in source_root.glob(str(rel_source)):
                if src.is_dir():
                    continue

                new_jobs.append({
                    'source': src,
                    'target': job['target'],
                })
            print_log(f"Staging job from todo_list: {source} -> Expanding to {len(new_jobs)} rows")
            expanded_jobs.extend(new_jobs)
        else:
            # No wildcards, just add the single file to the queue
            # Just a single file
            print_log(f"Staging job from todo_list: {source}")
            expanded_jobs.append({
                'source': source,
                'target': job['target'],
            })

        for exjob in expanded_jobs:
            source = exjob['source']

            # No wildcards, process the path directly - if it hasn't already
            # been processed.
            if source in done:
                continue
            done.add(source)

            original, source, staging, target, skip_copy = resolve_target(
                source=source,
                target=job["target"],
                original_root=job['original_root'],
                source_root=job['source_root'],
                staging_root=job['staging_root'],
                target_root=job['target_root'],
                replacements=path_replacements,
                no_log=job["no_log"],
            )
            tables = job.get('tables', None)
            if use_extra_kwargs:
                process_kwargs = {k: v for k, v in job.items() if k not in (
                    "source", "target", "source_root", "original_root", "target_root", "staging_root", "tables")}
                process_kwargs['replace_func'] = replace_func
            else:
                # hack to remove worse global code, need to cleanup
                process_kwargs = {}

            # process_func can either be
            # update_db_table_ids or process_file
            staged_tasks.append({
                'original': original,
                'source': source,
                'staging': staging,
                'target': target,
                'tables': tables,
                'skip_copy': skip_copy,
                'process_kwargs': process_kwargs,
                'process_func': process_func,
            })
    return staged_tasks


def process_file(
        original: Path,
        source: Path,
        staging: Path,
        target: Path,
        replacements: dict,
        replace_func,
        tables: dict = None,
        copy_only: bool = False,
        no_log: bool = False,
) -> None:
    if tables is None:
        tables = dict()

    if not staging:
        raise Exception('What do you want me to do with no input?')

    # Files only.
    if staging.is_dir():
        return

    if not no_log:
        print_log("Processing", staging)

    if copy_only:
        # No need to do any further checks.
        return
    elif staging.suffix == ".db":
        # If it's "library.db", save it for later (see comment at declaration):
        if staging.name == "library.db":
            # TODO: WE REALLY NEED TO GET RID OF GLOBALS!
            global LIBRARY_DB_SOURCE_PATH, LIBRARY_DB_STAGING_PATH
            LIBRARY_DB_SOURCE_PATH = source
            LIBRARY_DB_STAGING_PATH = staging
            rich.print(f'[yellow]!!!CHANGE GLOBAL: {LIBRARY_DB_SOURCE_PATH=}, {LIBRARY_DB_STAGING_PATH=}')
        # sqlite file. In this case table specifies which tables within that file have columns to check.
        # Iterate over those.
        for table, kwargs in tables.items():
            print_log("Processing table", table)
            # The remaining function arguments (**kwards) contain the details about the columns to process.
            # See update_db_table and/or the todo_list.
            # JON FIXME: the replacements dict probably needs to be wrt to staging, previously wrt to target
            update_db_table(file=staging, replace_dict=replacements, replace_func=replace_func, table=table, **kwargs)
    elif staging.suffix == ".xml" or staging.suffix == ".nfo":
        update_xml(file=staging, replace_dict=replacements, replace_func=replace_func)
    elif staging.suffix == ".mblink":
        # .mblink files only contain a path, nothing else.
        with open(staging, "r", encoding="utf-8") as f:
            path = f.read()
        path, modified, ignored, wrns = replace_func(path, replacements)
        if wrns:
            rich.print('[yellow]WARNING(process_file.1)')
        for warning in wrns:
            print_log(warning)
        print_log(f"Processed {modified + ignored} paths, {modified} paths have been modified.")
        with open(staging, "w", encoding="utf-8") as f:
            f.write(path)
    elif staging.suffix == ".json":
        # There are also json files with the ending .js but I haven't found any with paths.
        # Load the file by the json module (resulting in a dict or list object) and process
        # them by recursive_path_replacer which handles these structures.
        with open(staging, "r", encoding="utf-8") as f:
            j = json.load(f)
        j, modified, ignored, wrns = replace_func(j, replacements)
        if wrns:
            rich.print('[yellow]WARNING(process_file.2)')
        for warning in wrns:
            print_log(warning)
        print_log(f"Processed {modified + ignored} paths, {modified} paths have been modified.")
        with open(staging, "w", encoding="utf-8") as f:
            # indent 2 seems to be the default formatting for jellyfin json files.
            json.dump(j, f, indent=2)

    # If we're updating path ids we also need to check the paths of the files themselves
    # and move them if they're relative to a path.
    # This obviously leaves empty folders behind, which are cleaned up afterwards.
    if replace_func == nested_id_path_replacer:
        # I dont think this does anything, we can handle this elsewhere
        source = target
        target, modified, ignored, wrns = nested_id_path_replacer(source, replacements)
        if wrns:
            rich.print('[yellow]WARNING(process_file.3)')
        for warning in wrns:
            print_log(warning)
        if modified:
            print_log("Changing ID in filepath: ->", target)
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)


def update_db_table_ids(
        original,
        source,
        staging,
        target,
        tables,
        IDS=None,
        # **kwargs
):
    """
    Derived/copied from update_db_table.
    I couldn't see a good way to do this without copying. The data structures and processing are too different for path and id jobs.

    OLD COMMENT:
        Note: kwargs is due to how process_files works. It passes a lot of stuff from the
        job list that's not needed here.

    MY COMMENT:
        NO! Bad! DO IT BETTER! GFAGFGAJK!@!!!
    """
    if not os.path.exists(staging):
        print_log(f"Database staging={staging} does not exist, skipping")
        return

    print_log("Updating Item IDs in database... ")
    assert IDS is not None

    # Initialize sqlite3 objects
    con = sqlite3.connect(staging)
    cur = con.cursor()

    updated_ids_count = 0
    # That's a very nested loop and could probably be written more efficiently using
    # multiprocessing and more advanced sqlite queries.
    for table, columns_by_id_type in tables.items():
        for id_type, columns in columns_by_id_type.items():
            for column in columns:
                print_log(f"Updating {column} IDs in table {table}...")
                # See comment about iterating over rows while modifying them in update_db_table.
                try:
                    rows = [r for r in cur.execute(f"SELECT DISTINCT `{column}` from `{table}`")]
                except sqlite3.OperationalError:
                    print_log(f'ERROR: selecting distinct row from table={table} column={column} in {staging}')
                    raise

                progress = 0
                rowcount = len(rows)
                t = time()
                for old_id, in rows:
                    progress += 1
                    # Print the progress every second. Note: this is the only usage of the "progress" variable.
                    now = time()
                    if now - t > 1:
                        print_log(f"Progress: {progress} / {rowcount} rows")
                        t = now
                    if old_id in IDS[id_type]:
                        new_id = IDS[id_type][old_id]
                        try:
                            cur.execute(f"UPDATE `{table}` SET `{column}` = ? WHERE `{column}` = ?", (new_id, old_id))
                        except sqlite3.IntegrityError:
                            col_names  = [x[0] for x in cur.execute(f"SELECT name FROM PRAGMA_TABLE_INFO('{table}')")]
                            rows = [x for x in cur.execute(f"SELECT * FROM `{table}` WHERE `{column}` = ?", (old_id,))]
                            rows = [dict(zip(col_names, row)) for row in rows]
                            print_log(f"Encountered {len(rows)} duplicated entries")
                            for i, row in enumerate(rows):
                                print_log(f"Deleting ({i + 1}/{len(rows)}): ", row)
                            cur.execute(f"DELETE FROM `{table}` WHERE `{column}` = ?", (old_id,))
                        updated_ids_count += 1

    # Write the updated database back to the file.
    con.commit()
    con.close()
    print_log(f"{updated_ids_count} IDs updated.")


def get_ids(LIBRARY_DB_STAGING_PATH):
    rich.print(f'[green] Connect to LIBRARY_DB_STAGING_PATH={LIBRARY_DB_STAGING_PATH}')
    con = sqlite3.connect(LIBRARY_DB_STAGING_PATH)
    cur = con.cursor()

    id_replacements_bin = dict()
    for guid, item_type, path in cur.execute("SELECT `guid`, `type`, `Path` FROM `TypedBaseItems`"):
        if not path or path.startswith("%"):
            continue

        # Source: https://github.com/jellyfin/jellyfin/blob/7e8428e588b3f0a0574da44081098c64fe1a47d7/Emby.Server.Implementations/Library/LibraryManager.cs#L504 # noqa
        new_guid = get_dotnet_MD5(item_type + path)
        # Omit IDs that haven't changed at all. Happens if not _all_ paths are modified
        if new_guid != guid:
            id_replacements_bin[guid] = new_guid

    ### Adapted from id_scanner
    id_replacements_str               = {bid2sid(k): bid2sid(v) for k, v in id_replacements_bin.items()}
    id_replacements_str_dash          = {sid2did(k): sid2did(v) for k, v in id_replacements_str.items()}
    id_replacements_ancestor_str      = {convert_ancestor_id(k): convert_ancestor_id(v) for k, v in id_replacements_str.items()}
    id_replacements_ancestor_bin      = {sid2bid(k): sid2bid(v) for k, v in id_replacements_ancestor_str.items()}
    id_replacements_ancestor_str_dash = {sid2did(k): sid2did(v) for k, v in id_replacements_ancestor_str.items()}

    IDS = {
        "bin": id_replacements_bin,
        "str": id_replacements_str,
        "str-dash": id_replacements_str_dash,
        "ancestor-bin": id_replacements_ancestor_bin,
        "ancestor-str": id_replacements_ancestor_str,
        "ancestor-str-dash": id_replacements_ancestor_str_dash,
    }
    ### End of adapted code

    # Check for collisions between old and new ids in both the normal and ancestor format.
    # If there are collisions, get the (new) filepaths causing them
    uniques = set()
    duplicates = list()
    for id in id_replacements_str.values():
        if id in uniques:
            duplicates.append(id)
        else:
            uniques.add(id)

    # if there are duplicates, find the matching old_ids to query the lines from the database
    if duplicates:
        old_ids = []
        for k, v in id_replacements_str.items():
            if v in duplicates:
                old_ids.append(sid2bid(k))

        duplicates_new = [next(cur.execute("SELECT `guid`, `Path` FROM `TypedBaseItems` WHERE `guid` = ?", (guid,))) for guid in old_ids]
        # also fetch the old paths for better understanding/debugging
        con.close()
        con = sqlite3.connect(LIBRARY_DB_SOURCE_PATH)
        cur = con.cursor()
        duplicates_old = [next(cur.execute("SELECT `guid`, `Path` FROM `TypedBaseItems` WHERE `guid` = ?", (guid,))) for guid in old_ids]
        duplicates_old = dict(duplicates_old)
        con.close()

        print_log(f"Warning! {len(duplicates)} duplicates detected within new ids. This indicates that you're "
                  f"merging media files from different directories into fewer ones. If that's the case for all the "
                  f"collisions listed below, you can likely ignore this warning, otherwise recheck your path settings. "
                  f"IMPORTANT: The duplicated entries will be removed from the database. You got a backup of the "
                  f"database, right?")
        print_log("Duplicates: ")
        for id, newpath in duplicates_new:
            print_log(f"  Item ID: {bid2sid(id)},  Paths (old -> new): {duplicates_old[id]} -> {newpath}")
        input("Press Enter to continue or CTRL+C to abort. ")
    return IDS


def update_file_dates(LIBRARY_DB_STAGING_PATH, seen_tasks):
    print_log("Updating file dates... Note: Reading file dates seems to be quite slow. "
              "This will take a couple minutes")

    con = sqlite3.connect(LIBRARY_DB_STAGING_PATH)
    cur = con.cursor()

    rows = [r for r in cur.execute("SELECT `rowid`, `Path`, `DateCreated`, `DateModified` FROM `TypedBaseItems`")]

    import ubelt as ub
    import kwutil
    target_to_staging = {r['target']: r['staging'] for r in ub.flatten(seen_tasks)}
    print(f'target_to_staging = {ub.urepr(target_to_staging, nl=1)}')
    print(f'rows = {ub.urepr(rows, nl=1)}')
    pman = kwutil.ProgressManager()
    with pman:
        for rowid, target, date_created, date_modified in pman.ProgIter(rows, desc='update dates'):
            if not target:
                continue
            # Determine file path as seen by this script (see FS_PATH_REPLACEMENTS for details)
            # Code taken from get_target
            # print(f'FS_PATH_REPLACEMENTS={FS_PATH_REPLACEMENTS}')
            target, idgaf1, idgaf2, wrns = nested_root_path_replacer(target, to_replace=FS_PATH_REPLACEMENTS)
            for warning in wrns:
                print_log(warning)
            staging = target_to_staging.get(target, target)
            staging = Path(staging)

            if not staging.exists():
                rich.print(f"[yellow]File doesn't seem to exist; can't update its dates in the database: {staging!r}")
                continue

            cur.execute("UPDATE `TypedBaseItems` SET `Path` = ? WHERE `rowid` = ?",
                        (os.fspath(staging), rowid))

            date_created_ns  = jf_date_str_to_python_ns(date_created)
            date_modified_ns = jf_date_str_to_python_ns(date_modified)

            if date_created_ns >= 0 and date_modified_ns >= 0:
                continue

            filestats = os.stat(staging)

            if date_created_ns < 0:
                new_date_created = get_datestr_from_python_time_ns(filestats.st_ctime_ns)
                cur.execute("UPDATE `TypedBaseItems` SET `DateCreated` = ? WHERE `rowid` = ?",
                            (new_date_created, rowid))
            if date_modified_ns < 0:
                new_date_modified = get_datestr_from_python_time_ns(filestats.st_mtime_ns)
                cur.execute("UPDATE `TypedBaseItems` SET `DateModified` = ? WHERE `rowid` = ?",
                            (new_date_modified, rowid))

    con.commit()
    print_log("Done.")


def execute_tasks(staged_tasks):
    import pandas as pd
    import rich
    rich.print('[blue]Staged Tasks:')
    df = pd.DataFrame(t for t in staged_tasks)
    rich.print(df)
    rich.print('[blue]Executing Tasks:')
    for task in staged_tasks:
        task = task.copy()
        process_func = task.pop('process_func')
        process_kwargs = task.pop('process_kwargs')
        original = task.pop('original')
        source = task.pop('source')
        staging = task.pop('staging')
        target = task.pop('target')
        tables = task.pop('tables')
        skip_copy = task.pop('skip_copy')
        no_log = False
        if not skip_copy:
            if not staging.parent.exists():
                staging.parent.mkdir(parents=True)
            if not no_log:
                print_log(f"Copy... {source} -> {staging}", end=" ")
            copy(source, staging)
            if not no_log:
                print_log("Done.")

        process_func(source=source, staging=staging, target=target,
                     original=original, tables=tables,
                     **process_kwargs)
    rich.print('[blue]Finished Tasks')


def main():
    import textwrap
    from rich.markup import escape
    print_log("")
    rich.print('[white]' + escape(textwrap.dedent(
        r"""
        ===========================================================================
         _ ____ _    _    _   _ ____ _ _  _    _  _ _ ____ ____ ____ ___ ____ ____
         | |___ |    |     \_/  |___ | |\ |    |\/| | | __ |__/ |__|  |  |  | |__/
        _| |___ |___ |___   |   |    | | \|    |  | | |__] |  \ |  |  |  |__| |  \

        ===========================================================================
        """)))
    print_log("Starting Jellyfin Database Migration")

    ### Copy relevant files and adjust all paths to the new locations.
    rich.print("[white]STEP 1. Copy relevant files and adjust all paths to the new locations.")

    seen_tasks = []

    staged_tasks = collect_files_to_process(
        TODO_LIST_PATHS,
        process_func=process_file,
        replace_func=nested_root_path_replacer,
        path_replacements=PATH_REPLACEMENTS,
        use_extra_kwargs=True,
    )
    seen_tasks.append(staged_tasks)
    execute_tasks(staged_tasks)

    ### Update IDs
    print_log("STEP2. Update IDs.")
    # Generate IDs based on those new paths and save them in the global variable
    IDS = get_ids(LIBRARY_DB_STAGING_PATH)
    # ID types occurring in paths (<- search for that to find another comment with more details if you missed it)
    # Include/Exclude types (see get_ids) to specify which are used for looking through paths.
    # Currently, all are included, just to be safe.
    id_replacements_path = {
        **IDS["ancestor-str"],
        **IDS["ancestor-str-dash"],
        **IDS["str"],
        **IDS["str-dash"],
        "target_path_slash": PATH_REPLACEMENTS["target_path_slash"]
    }
    print(f'id_replacements_path = {ub.urepr(id_replacements_path, nl=1)}')

    # To (mostly) reuse the same functions from step 1, the replacements dict needs to be updated with
    # id_replacements_path. It can't be replaced since it's also used to find the files (which uses the
    # same source -> target processing/conversion as step 1). In theory this alters the process since
    # the dict used to convert from source -> target is different, in reality, this is not an issue,
    # since step 1 only processes the roots of the paths (which cannot be similar to anything in
    # id_replacements_path).
    for i, job in enumerate(TODO_LIST_ID_PATHS):
        TODO_LIST_ID_PATHS[i]["replacements"] = id_replacements_path

    # import ubelt as ub
    # print(f'IDS = {ub.urepr(IDS, nl=1)}')

    # Replace all paths with ids - both in the file system and within files.
    rich.print("[white]STEP 3.1 Replace all paths with ids.")
    staged_tasks = collect_files_to_process(
        TODO_LIST_ID_PATHS,
        process_func=process_file,
        replace_func=nested_id_path_replacer,
        path_replacements={**PATH_REPLACEMENTS, **id_replacements_path},
        use_extra_kwargs=True,
    )
    seen_tasks.append(staged_tasks)
    execute_tasks(staged_tasks)

    # Clean up empty folders that may be left behind in the target directory
    #delete_empty_folders(todo, there might be multiple target roots)

    # Replace remaining ids.
    rich.print("[white]STEP 3.2 Replace remaining ids.")
    staged_tasks = collect_files_to_process(
        TODO_LIST_IDS,
        process_func=partial(update_db_table_ids, IDS=IDS),
        replace_func=None,
        path_replacements=PATH_REPLACEMENTS,
        use_extra_kwargs=False,
    )
    seen_tasks.append(staged_tasks)
    execute_tasks(staged_tasks)

    # Finally, update the file dates in the db.
    rich.print("[white]STEP 4. Update the file dates.")
    update_file_dates(LIBRARY_DB_STAGING_PATH, seen_tasks)

    print_log("")
    rich.print("[green]Jellyfin Database Migration complete.")

    # We don't actually need the following, mounting /staging/staged-data to config should work.
    # d1 = {k: getattr(config.STAGING, k) for k in dir(config.STAGING) if not k.startswith('_')}
    # d2 = {k: getattr(config.TARGET, k) for k in dir(config.STAGING) if not k.startswith('_')}

    # # Ensure we move directories in the right order
    # import networkx as nx
    # # Map destination paths to source paths
    # # path_mapping = {d2[k]: d1[k] for k in d1}
    # # Add nodes (only using destination paths)
    # G = nx.DiGraph()
    # for k, v in d2.items():
    #     G.add_node(v, key=k)
    # G.add_nodes_from(d2.values())
    # for path1 in d2.values():
    #     for path2 in d2.values():
    #         if path1 != path2 and str(path2).startswith(str(path1)):
    #             G.add_edge(path1, path2)  # path1 must be moved before path2
    # G = nx.transitive_reduction(G)
    # for k, v in d2.items():
    #     G.nodes[v]['key'] = k
    # nx.write_network_text(G)

    # # Perform a topological sort
    # ordered_moves = [G.nodes[node]['key'] for node in nx.topological_sort(G)]

    # lines = []
    # for k in ordered_moves:
    #     v1 = d1[k]
    #     v2 = d2[k]
    #     path = ub.Path(v1)
    #     dst = ub.Path(v2)

    #     # src = '/'.join([str(Path(*path.parts[0:-1])), path.parts[-1]])
    #     src = path
    #     # Trailing slash is crucial
    #     line = (f'test -e {v1} && rsync -avPR {src}/ {dst}/')

    #     # src = './' + path.name
    #     # line = (f'test -e {src} && mv {src} {dst}')
    #     lines.append(line)

    # accept_text = '\n'.join(lines)
    # # accept_text = ub.codeblock(
    # #     """
    # #     test -e /staging/staged-cached && rsync -avPR /staging/staged-cached /config/cache
    # #     test -e /staging/staged-config && rsync -avPR /staging/staged-config /config
    # #     test -e /staging/staged-data && rsync -avPR /staging/staged-data /config/data
    # #     test -e /staging/staged-ffmpeg && rsync -avPR /staging/staged-ffmpeg usr/lib/jellyfin-ffmpeg/ffmpeg
    # #     test -e /staging/staged-log && rsync -avPR /staging/staged-log /config/log
    # #     test -e /staging/staged-transcodes && rsync -avPR /staging/staged-transcodes /config/data/transcodes
    # #     """
    # # )
    # print(accept_text)
    # accept_fpath = config.STAGING_ROOT / 'accept.sh'
    # accept_fpath.write_text(accept_text)
    # # accept_fpath.chmod('u+x')

if __name__ == "__main__":
    main()
