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
import json
import os
import sqlite3
import xml.etree.ElementTree as ET

from pathlib import Path
import shutil
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
from jellyfin_migrator.utils import requires_permission
from jellyfin_migrator.utils import SudoCredentialRefresher
import logging
import textwrap
from contextlib import ExitStack

banner = textwrap.dedent(
    r"""
    ===========================================================================
     _ ____ _    _    _   _ ____ _ _  _    _  _ _ ____ ____ ____ ___ ____ ____
     | |___ |    |     \_/  |___ | |\ |    |\/| | | __ |__/ |__|  |  |  | |__/
    _| |___ |___ |___   |   |    | | \|    |  | | |__] |  \ |  |  |  |__| |  \

    ===========================================================================
    """)


try:
    # For DEV, but should make these optional
    import rich
    import ubelt as ub
except ImportError:
    raise

try:
    from line_profiler import profile
except ImportError:
    profile = ub.identity

logger = logging.getLogger(__name__)


@profile
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
    logger.info(f'[green]update_db_table, Connect to: file={file}')
    con = sqlite3.connect(file)
    with con:
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

        # column_names = list(json_columns) + list(path_columns) + list(jf_image_columns)
        # For the sql query the desired row names should be enclosed in ` ` and comma separated.
        # It's important to note that the json columns come first, followed by the path columns
        columns = ", ".join([f"`{e}`" for e in list(json_columns) + list(path_columns)] + list(jf_image_columns))

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
                logger.info(f"Progress: {progress} / {rows_count} rows")
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
                logger.info(f"Error with rowid {id}! Resulted in {len(row)} rows instead of 1. Skipping.")
                raise AssertionError('ERROR: should not get this')
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
            # old_rowdata = ub.dzip(column_names, row)

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
                    # if wrns:
                    #     logger.warn('[yellow]WARNING1')
                    for warning in wrns:
                        logger.warn(warning)
                    modified += mo
                    ignored  += ig
                    result[json_columns[i]] = json.dumps(data)
            for i, path in enumerate(paths):
                # One could also skip the empty objects here, but recursive_path_replacer handles them
                # just fine (leaves them untouched).
                path, mo, ig, wrns = replace_func(path, replace_dict)
                # if wrns:
                #     logger.warn('[yellow]WARNING2')
                for warning in wrns:
                    logger.warn(warning)
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
                    # print(f'old img_properties={img_properties}')
                    # print(f'replace_dict={replace_dict}')
                    # path = first property
                    img_properties[0], mo, ig, wnrs = replace_func(img_properties[0], replace_dict)
                    # if wrns:
                    #     logger.warn('[yellow]WARNING3')
                    for warning in wrns:
                        logger.warn(warning)
                    # print(f'new img_properties={img_properties}')
                    imgs[j] = "*".join(img_properties)
                    modified += mo
                    ignored  += ig
                imgs = "|".join(imgs)
                result[jf_image_columns[i]] = imgs

            new_rowdata = result

            # print(f'replace_dict = {ub.urepr(replace_dict, nl=1)}')
            # print(f'old_rowdata = {ub.urepr(old_rowdata, nl=1)}')
            # print(f'new_rowdata = {ub.urepr(new_rowdata, nl=1)}')

            new_rowdata = {k.lower(): v for k, v in new_rowdata.items()}
            # if 'path' in old_rowdata:
            #     if old_rowdata['path'] == '/data/jellyfin/media/music/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3':
            #         print(f'old_rowdata = {ub.urepr(old_rowdata, nl=1)}')
            #         print(f'new_rowdata = {ub.urepr(new_rowdata, nl=1)}')
            # if 'path' in new_rowdata:
            #     if new_rowdata['path'] == '/data/jellyfin/media/music/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3':
            #         raise Exception
            # if 'path' not in new_rowdata:
            #     if old_rowdata['path'] is not None:
            #         raise AssertionError('UNCHANGED PATH')

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

            # THIS IS WHERE PATH NAMES ARE REPLACED IN DATABASE FILES.
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
                logger.error(f"Error: {e}")
                logger.error(f"Query: {query}")
                logger.error(f"Args: {args}")
                raise
                exit()
            else:
                if cur.rowcount < 1:
                    # This was mainly for debugging purposes and shouldn't be reached anymore.
                    # Doesn't hurt to have it though.
                    logger.error("No data modified!")
                    logger.error(f"Query: {query}")
                    logger.error(f"Args: {args}")
                    raise
                    exit()
        logger.info(f"update_db_table, Processed {rows_count} rows in table {table}. ")
        logger.info(f"update_db_table, {modified} paths have been modified.")

        # Write the updated database back to the file.
        con.commit()
        con.execute("PRAGMA wal_checkpoint(FULL);")  # Flush WAL changes to main database

    # raise Exception


@profile
def update_xml(file: Path, replace_dict: dict, replace_func) -> None:
    """
    Walks through an XML file and checks *all* entries.
    WARNING: The documentation of this parser explicitly mentions that it's not hardened against
    known XML vulnerabilities. It is NOT suitable for unknown/unsafe XML files. Shouldn't be an
    issue here though.

    THIS IS A SLOW FUNCTION. WE SHOULD PARALLELIZE IF POSSIBLE.
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
        # if wrns:
        #     logger.warn('[yellow]WARNING(update_xml)')
        for warning in wrns:
            logger.warn(warning)
        modified += mo
        ignored  += ig
    logger.info(f"Processed {ignored + modified} elements. {modified} paths have been modified.")
    tree.write(file)  # , encoding="utf-8")


@profile
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

        # new_relpath, _, _, _ = nested_root_path_replacer(relpath, to_replace=replacements)

        # Sometimes moving a path needs to move to a new location because the
        # path contains part of the id and this handles that.
        new_relpath, *_ = nested_id_path_replacer(relpath, replacements)

        staging = staging_root / new_relpath
        # target_v1, idgaf1, idgaf2, wrns1 = nested_root_path_replacer(original_source, to_replace=replacements)
        # target_v2, idgaf1, idgaf2, wrns2 = nested_root_path_replacer(target_v1, to_replace=FS_PATH_REPLACEMENTS)
        # for warning in wrns1 + wrns2:
        # for warning in wrns1:
        #     logger.info(warning)
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
        target = target_root / new_relpath

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
    return original, source, staging, target, skip_copy


@profile
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
    logger.info('Calling collect_files_to_process')
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
            logger.info(f"Staging job from todo_list: {source} -> Expanding to {len(new_jobs)} rows")
            expanded_jobs.extend(new_jobs)
        else:
            # No wildcards, just add the single file to the queue
            # Just a single file
            logger.info(f"Staging job from todo_list: {source}")
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

            if 'replacements' in process_kwargs:
                process_kwargs['replacements'].update(path_replacements)

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


@profile
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

    no_log = False
    if not no_log:
        logger.info(f"Processing: {staging}")

    if copy_only:
        # No need to do any further checks.
        logger.info("Copy only")
        return
    elif staging.suffix == ".db":
        # debug_staging_library('PROCESS_FILE-BEFORE')
        # sqlite file. In this case table specifies which tables within that file have columns to check.
        # Iterate over those.
        for table, kwargs in tables.items():
            logger.info(f"Processing table: {table}")
            # The remaining function arguments (**kwargs) contain the details about the columns to process.
            # See update_db_table and/or the todo_list.
            # JON FIXME: the replacements dict probably needs to be wrt to staging, previously wrt to target
            update_db_table(file=staging, replace_dict=replacements, replace_func=replace_func, table=table, **kwargs)
        # debug_staging_library('PROCESS_FILE-AFTER')
    elif staging.suffix == ".xml" or staging.suffix == ".nfo":
        update_xml(file=staging, replace_dict=replacements, replace_func=replace_func)
    elif staging.suffix == ".mblink":
        # .mblink files only contain a path (to what seems to be a media library), nothing else.
        with open(staging, "r", encoding="utf-8") as f:
            path = f.read()
        new_path, modified, ignored, wrns = replace_func(path, replacements)
        # if wrns:
        #     logger.warn('[yellow]WARNING(process_file.1)')
        for warning in wrns:
            logger.warn(warning)
        logger.info(f"Processed {modified + ignored} paths, {modified} paths have been modified.")
        with open(staging, "w", encoding="utf-8") as f:
            f.write(new_path)
    elif staging.suffix == ".json":
        # There are also json files with the ending .js but I haven't found any with paths.
        # Load the file by the json module (resulting in a dict or list object) and process
        # them by recursive_path_replacer which handles these structures.
        with open(staging, "r", encoding="utf-8") as f:
            j = json.load(f)
        j, modified, ignored, wrns = replace_func(j, replacements)
        # if wrns:
        #     logger.warn('[yellow]WARNING(process_file.2)')
        for warning in wrns:
            logger.warn(warning)
        logger.info(f"Processed {modified + ignored} paths, {modified} paths have been modified.")
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
        # if wrns:
        #     logger.warn('[yellow]WARNING(process_file.3)')
        for warning in wrns:
            logger.warn(warning)
        if modified:
            logger.info(f"Changing ID in filepath: -> {target}")
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)


@profile
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
    """
    if not os.path.exists(staging):
        logger.info(f"Database staging={staging} does not exist, skipping")
        return

    logger.info("Updating Item IDs in database... ")
    assert IDS is not None
    # debug_staging_library('Before Update IDS', show_table=True)

    # Initialize sqlite3 objects
    con = sqlite3.connect(staging)
    with con:
        cur = con.cursor()

        updated_ids_count = 0
        # That's a very nested loop and could probably be written more efficiently using
        # multiprocessing and more advanced sqlite queries.
        for table, columns_by_id_type in tables.items():
            for id_type, columns in columns_by_id_type.items():
                typed_id_mapper = IDS[id_type]

                for column in columns:
                    logger.info(f"Updating {column} IDs in table {table}...")
                    # See comment about iterating over rows while modifying them in update_db_table.
                    try:
                        rows = [r for r in cur.execute(f"SELECT DISTINCT `{column}` from `{table}`")]
                    except sqlite3.OperationalError:
                        logger.info(f'ERROR: selecting distinct row from table={table} column={column} in {staging}')
                        raise

                    rows_updated = 0
                    rows_skipped = 0

                    progress = 0
                    rowcount = len(rows)
                    t = time()
                    for old_id, in rows:
                        progress += 1
                        # Print the progress every second. Note: this is the only usage of the "progress" variable.
                        now = time()
                        if now - t > 1:
                            logger.info(f"Progress: {progress} / {rowcount} rows")
                            t = now
                        if old_id in typed_id_mapper:
                            new_id = typed_id_mapper[old_id]
                            try:
                                cur.execute(f"UPDATE `{table}` SET `{column}` = ? WHERE `{column}` = ?", (new_id, old_id))
                            except sqlite3.IntegrityError:
                                col_names  = [x[0] for x in cur.execute(f"SELECT name FROM PRAGMA_TABLE_INFO('{table}')")]
                                rows = [x for x in cur.execute(f"SELECT * FROM `{table}` WHERE `{column}` = ?", (old_id,))]
                                rows = [dict(zip(col_names, row)) for row in rows]
                                logger.info(f"Encountered {len(rows)} duplicated entries")
                                for i, row in enumerate(rows):
                                    logger.info(f"Deleting ({i + 1}/{len(rows)}): {row}")
                                cur.execute(f"DELETE FROM `{table}` WHERE `{column}` = ?", (old_id,))
                            updated_ids_count += 1
                            rows_updated += 1
                        else:
                            rows_skipped += 1
                    # if table == 'TypedBaseItems' and column == 'guid':
                    #     debug = [r for r in cur.execute(f"SELECT DISTINCT `{column}`,`Path` from `{table}`")]
                    #     print(f'debug = {ub.urepr(debug, nl=1)}')
                    #     print('update/skip', rows_updated, rows_skipped)
                    #     import xdev
                    #     xdev.embed()
                    #     import sys
                    #     sys.exit(1)

        # Write the updated database back to the file.
        con.commit()
        con.execute("PRAGMA wal_checkpoint(FULL);")  # Flush WAL changes to main database
        con.commit()

    # debug_staging_library('After WAL', show_table=True)
    logger.info(f"{updated_ids_count} IDs updated.")


@profile
def get_ids(LIBRARY_DB_STAGING_PATH, LIBRARY_DB_SOURCE_PATH, target_data_path):
    logger.info(f'[green] Connect to LIBRARY_DB_STAGING_PATH={LIBRARY_DB_STAGING_PATH}')

    staging_uri = 'file:' + str(LIBRARY_DB_STAGING_PATH) + '?mode=ro&immutable=1'
    assert os.path.exists(LIBRARY_DB_STAGING_PATH)
    con = sqlite3.connect(staging_uri, uri=True)

    target_data_path = os.fspath(target_data_path)

    # temp_path = ub.Path(LIBRARY_DB_STAGING_PATH).augment(stemsuffix='tmp')
    # ub.Path(LIBRARY_DB_STAGING_PATH).copy(temp_path, overwrite=True)
    # con = sqlite3.connect(str(temp_path))
    with con:
        cur = con.cursor()

        id_replacements_bin = dict()
        for guid, item_type, path in cur.execute("SELECT `guid`, `type`, `Path` FROM `TypedBaseItems`"):
            if not path or path.startswith("%"):
                # print('SKIP')
                continue
            # print(f'COMPUTE REPLACEMENT GUID FOR: path={path}')
            if path.startswith(target_data_path):
                # HACK
                continue

            # Source: https://github.com/jellyfin/jellyfin/blob/7e8428e588b3f0a0574da44081098c64fe1a47d7/Emby.Server.Implementations/Library/LibraryManager.cs#L504 # noqa
            new_guid = get_dotnet_MD5(item_type + path)
            # Omit IDs that haven't changed at all. Happens if not _all_ paths are modified
            if new_guid != guid:
                id_replacements_bin[guid] = new_guid
                # print(f'OLD {guid.hex()}, NEW={new_guid.hex()}')

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
            src_uri = 'file:' + str(LIBRARY_DB_SOURCE_PATH) + '?mode=ro&immutable=1'
            src_con = sqlite3.connect(src_uri, uri=True)
            with src_con:
                cur = src_con.cursor()
                duplicates_old = [next(cur.execute("SELECT `guid`, `Path` FROM `TypedBaseItems` WHERE `guid` = ?", (guid,))) for guid in old_ids]
                duplicates_old = dict(duplicates_old)

            logger.info(f"Warning! {len(duplicates)} duplicates detected within new ids. This indicates that you're "
                        f"merging media files from different directories into fewer ones. If that's the case for all the "
                        f"collisions listed below, you can likely ignore this warning, otherwise recheck your path settings. "
                        f"IMPORTANT: The duplicated entries will be removed from the database. You got a backup of the "
                        f"database, right?")
            logger.info("Duplicates: ")
            for id, newpath in duplicates_new:
                logger.info(f"  Item ID: {bid2sid(id)},  Paths (old -> new): {duplicates_old[id]} -> {newpath}")
            input("Press Enter to continue or CTRL+C to abort. ")
    con.close()
    return IDS


@profile
def update_file_dates(LIBRARY_DB_STAGING_PATH, FS_PATH_REPLACEMENTS, seen_tasks):
    logger.info("Updating file dates... Note: Reading file dates seems to be quite slow. "
                "This will take a couple minutes")

    con = sqlite3.connect(LIBRARY_DB_STAGING_PATH)
    with con:
        cur = con.cursor()

        rows = [r for r in cur.execute("SELECT `rowid`, `Path`, `DateCreated`, `DateModified` FROM `TypedBaseItems`")]

        import ubelt as ub
        import kwutil
        target_to_staging = {r['target']: r['staging'] for r in ub.flatten(seen_tasks)}
        # logger.info(f'target_to_staging = {ub.urepr(target_to_staging, nl=1)}')
        # logger.info(f'rows = {ub.urepr(rows, nl=1)}')
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
                    logger.info(warning)

                staging = target_to_staging.get(target, target)
                staging = Path(staging)

                try:
                    _exists = staging.exists()
                except PermissionError:
                    _exists = False

                if not _exists:
                    logger.warn(f"[yellow]File doesn't seem to exist; can't update its dates in the database: {staging!r}")
                    continue

                try:
                    date_created_ns  = jf_date_str_to_python_ns(date_created)
                except Exception as ex:
                    logger.error(str(ex))
                    date_created_ns = -1

                try:
                    date_modified_ns = jf_date_str_to_python_ns(date_modified)
                except Exception as ex:
                    logger.error(str(ex))
                    date_modified_ns = -1

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

    logger.info("Done.")


@profile
def copy(src, dst):
    """
    copy variant that attempts to handle permission issues
    """
    try:
        shutil.copy(src, dst)
    except OSError:
        # Attempt with permissions
        if ub.POSIX:
            ub.cmd(['sudo', 'cp', src, dst], check=True)
        else:
            raise


@profile
def execute_tasks(staged_tasks):
    try:
        import pandas as pd
    except ImportError:
        ...
    else:
        df = pd.DataFrame(t for t in staged_tasks)
        logger.info('Staged Task Table: \n' + str(df))

    logger.info('[blue]Executing Tasks:')
    for task in staged_tasks:
        task = task.copy()
        process_func = task.pop('process_func')
        process_kwargs = task.pop('process_kwargs')
        original = task.pop('original')
        source = task.pop('source')
        if str(source).endswith('.db-shm'):
            logger.info(f"SKIP {source}... has special handling")
            continue
        if str(source).endswith('.db-wal'):
            logger.info(f"SKIP {source}... has special handling")
            continue
        staging = task.pop('staging')
        target = task.pop('target')
        tables = task.pop('tables')
        skip_copy = task.pop('skip_copy')
        no_log = False
        if not skip_copy:
            if not staging.parent.exists():
                staging.parent.mkdir(parents=True)
            if not no_log:
                logger.info(f"Copy... {source} -> {staging}")
            # HACK:
            copy(source, staging)
            if source.name in {'library.db', 'jellyfin.db'}:
                logger.info('HACK: also copy wal and shm files')
                src2 = ub.Path(source).augment(ext='.db-shm')
                if src2.exists():
                    dst2 = ub.Path(staging).augment(ext='.db-shm')
                    logger.info(f'dst2 = {ub.urepr(dst2, nl=1)}')
                    copy(src2, dst2)
                src2 = ub.Path(source).augment(ext='.db-wal')
                if src2.exists():
                    dst3 = ub.Path(staging).augment(ext='.db-wal')
                    logger.info(f'dst3 = {ub.urepr(dst3, nl=1)}')
                    copy(src2, dst3)
                con = sqlite3.connect(staging)
                with con:
                    con.execute("PRAGMA wal_checkpoint(FULL);")
                    con.commit()
                    con.execute("PRAGMA VACUUM;")
                    con.commit()
                    con.execute("PRAGMA integrity_check;")
                    con.commit()
                con.close()
                # dst3.delete()
                # dst2.delete()
        else:
            logger.info(f"SKIP Copy... {source} -> {staging}")

        process_func(source=source, staging=staging, target=target,
                     original=original, tables=tables,
                     **process_kwargs)
    logger.info('[blue]Finished Tasks')
    # debug_staging_library('AFTER EXCUTE TASKS', show_table=True)


@profile
def setup_logger(log_file):
    """
    Configure the application level logger.
    """
    from rich.logging import RichHandler
    from rich.markup import render

    log_fpath = ub.Path(log_file)
    if not log_fpath.parent.exists():
        raise Exception('Log directory does not exist')

    def strip_rich_markup(message: str) -> str:
        return str(render(message))

    logger.setLevel(logging.DEBUG)
    # Define log format with time
    # log_format = "%(asctime)s - %(levelname)s - %(message)s"
    # log_format = "%(asctime)s - %(levelname)s - %(funcName)s - %(message)s"
    log_format = "%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler with Rich
    console_handler = RichHandler(markup=True)
    console_handler.setLevel(logging.DEBUG)
    # console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(funcName)s - %(message)s", datefmt=date_format))

    # File handler without Rich formatting
    class NoRichFileHandler(logging.FileHandler):
        def emit(self, record):
            record.msg = strip_rich_markup(record.msg)
            super().emit(record)

    file_handler = NoRichFileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    # file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(funcName)s - %(message)s", datefmt=date_format))

    # Add handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def setup_logger_threaded(log_file):
    """
    Configure the application level logger with background thread processing.
    """
    import logging
    import logging.handlers
    import queue
    from rich.logging import RichHandler
    from rich.markup import render
    import ubelt as ub

    log_fpath = ub.Path(log_file)
    if not log_fpath.parent.exists():
        raise Exception('Log directory does not exist')

    def strip_rich_markup(message: str) -> str:
        return str(render(message))

    # Create a queue for log records
    log_queue = queue.Queue(-1)  # No limit on queue size

    # Create and configure the logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create a QueueHandler which puts records in the queue
    queue_handler = logging.handlers.QueueHandler(log_queue)
    logger.addHandler(queue_handler)

    # Define log format with time
    log_format = "%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Create handlers that will do the actual logging
    # Console handler with Rich
    console_handler = RichHandler(markup=True)
    console_handler.setLevel(logging.DEBUG)

    # File handler without Rich formatting
    class NoRichFileHandler(logging.FileHandler):
        def emit(self, record):
            record.msg = strip_rich_markup(record.msg)
            super().emit(record)

    file_handler = NoRichFileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

    # Create a QueueListener which will process the queue
    listener = logging.handlers.QueueListener(
        log_queue,
        console_handler,
        file_handler,
        respect_handler_level=True  # Respect handler levels
    )

    # Start the listener
    listener.start()

    # Return both the logger and the listener in case you need to stop it later
    return logger, listener


@profile
def main(argv=True, **kwargs):
    """
    Main entry point.

    Parse arguments, read configuration, prepare migration, copy migratable
    data to a staging directory.
    """
    import pickle
    from jellyfin_migrator import config as config_mod
    config = config_mod.JellyfinMigratorConfig.cli(argv=argv, data=kwargs, strict=True)
    import rich
    from rich.markup import escape
    if 0:
        requested_config_text = ub.urepr(config, nl=2)
        rich.print('config = ' + escape(requested_config_text))
    config = config_mod.postprocess_config(config)

    # Convert the config into a form suitable for the original logic
    migration_datastructures = config_mod.prepare_migration_datastructures(config)
    PATH_REPLACEMENTS = migration_datastructures['PATH_REPLACEMENTS']
    TODO_LIST_PATHS_1 = migration_datastructures['TODO_LIST_PATHS_1']
    TODO_LIST_PATHS_2 = migration_datastructures['TODO_LIST_PATHS_2']
    TODO_LIST_ID_PATHS = migration_datastructures['TODO_LIST_ID_PATHS']
    TODO_LIST_IDS = migration_datastructures['TODO_LIST_IDS']
    FS_PATH_REPLACEMENTS = migration_datastructures['FS_PATH_REPLACEMENTS']
    target_data_path = config['target']['data']

    if config.thread_logs:
        setup_logger_threaded(config.log_file)
    else:
        setup_logger(config.log_file)

    if config.debug_path is not None:
        config.debug_path = ub.Path(config.debug_path).ensuredir()

    logger.info("")
    logger.info('\n[white]' + escape(banner))
    logger.info("Starting Jellyfin Database Migration")
    resolved_config_text = ub.urepr(config, nl=2)
    logger.info('config = ' + escape(resolved_config_text))

    contexts = []
    if requires_permission(config):
        logger.info(ub.paragraph(
            '''
            Permission will be required to read database files. To continue
            provide permission to this script, or modify the permissions so
            this script can read the files in the source directories
            '''))
        ub.cmd('sudo --validate', verbose=3)
        # Once we have them, keep refreshing them
        credential_refresher = SudoCredentialRefresher()  # NOQA
        credential_refresher.start()
        contexts.append(credential_refresher)

    with ExitStack() as stack:
        for context in contexts:
            stack.enter_context(context)

        ### Copy relevant files and adjust all paths to the new locations.
        logger.info("[white]STEP 1. Copy relevant files and adjust all paths to the new locations.")

        if not config.media_replacements:
            logger.warn('NO MEDIA REPLACEMENTS WERE GIVEN. This might be a problem')

        seen_tasks = []

        staged_tasks1 = collect_files_to_process(
            TODO_LIST_PATHS_1,
            process_func=process_file,
            replace_func=nested_root_path_replacer,
            path_replacements=PATH_REPLACEMENTS,
            use_extra_kwargs=True,
        )
        seen_tasks.append(staged_tasks1)
        execute_tasks(staged_tasks1)

        # Pull out the library db path explicitly
        # Since library.db will be needed throughout the process, its location is stored
        # here once it's been moved and updated with the new paths.
        LIBRARY_DB_STAGING_PATH = None
        LIBRARY_DB_SOURCE_PATH = None
        for task in staged_tasks1:
            if task['original'].name == 'library.db':
                LIBRARY_DB_STAGING_PATH = task['staging']
                LIBRARY_DB_SOURCE_PATH = task['source']
        assert LIBRARY_DB_SOURCE_PATH is not None

        ### Update IDs
        logger.info("STEP2. Get IDs.")
        # Generate IDs based on those new paths and save them in the global variable
        IDS = get_ids(LIBRARY_DB_STAGING_PATH, LIBRARY_DB_SOURCE_PATH, target_data_path)
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
        logger.info(f'id_replacements_path = {ub.urepr(id_replacements_path, nl=1)}')

        # debug_staging_library('BEFORE GET IDS', show_table=True)
        path_replacements2 = {**PATH_REPLACEMENTS, **id_replacements_path}
        logger.info(f'path_replacements2 = {ub.urepr(path_replacements2, nl=1)}')

        staged_tasks2 = collect_files_to_process(
            TODO_LIST_PATHS_2,
            process_func=process_file,
            replace_func=nested_root_path_replacer,
            path_replacements=path_replacements2,
            use_extra_kwargs=True,
        )
        seen_tasks.append(staged_tasks2)
        execute_tasks(staged_tasks2)

        # debug_staging_library('AFTER GET IDS', show_table=True)

        # To (mostly) reuse the same functions from step 1, the replacements dict needs to be updated with
        # id_replacements_path. It can't be replaced since it's also used to find the files (which uses the
        # same source -> target processing/conversion as step 1). In theory this alters the process since
        # the dict used to convert from source -> target is different, in reality, this is not an issue,
        # since step 1 only processes the roots of the paths (which cannot be similar to anything in
        # id_replacements_path).
        for i, job in enumerate(TODO_LIST_ID_PATHS):
            TODO_LIST_ID_PATHS[i]["replacements"].update(id_replacements_path)

        # import ubelt as ub
        # print(f'IDS = {ub.urepr(IDS, nl=1)}')
        if config.debug_path is not None:
            step3_dpath = (config.debug_path / 'before_step3').ensuredir()
            with open(step3_dpath / 'PATH_REPLACEMENTS.pkl', 'wb') as f:
                pickle.dump(PATH_REPLACEMENTS, f)
            with open(step3_dpath / 'id_replacements_path.pkl', 'wb') as f:
                pickle.dump(id_replacements_path, f)
            with open(step3_dpath / 'TODO_LIST_ID_PATHS.pkl', 'wb') as f:
                pickle.dump(TODO_LIST_ID_PATHS, f)

        # Replace all paths with ids - both in the file system and within files.
        logger.info("[white]STEP 3.1 Replace all paths with ids.")
        # logger.info(f'PATH_REPLACEMENTS={PATH_REPLACEMENTS}')
        # debug_staging_library('BEFORE REPLACE WITH IDS', show_table=True)

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
        logger.info("[white]STEP 3.2 Replace remaining ids.")
        # debug_staging_library('AFTER REPLACE WITH IDS', show_table=True)
        # raise Exception
        staged_tasks = collect_files_to_process(
            TODO_LIST_IDS,
            process_func=partial(update_db_table_ids, IDS=IDS),
            replace_func=None,
            path_replacements=PATH_REPLACEMENTS,
            use_extra_kwargs=False,
        )
        seen_tasks.append(staged_tasks)
        execute_tasks(staged_tasks)

        if config.debug_path is not None:
            step4_dpath = (config.debug_path / 'before_step4').ensuredir()
            with open(step4_dpath / 'LIBRARY_DB_STAGING_PATH.pkl', 'wb') as f:
                pickle.dump(LIBRARY_DB_STAGING_PATH, f)
            with open(step4_dpath / 'FS_PATH_REPLACEMENTS.pkl', 'wb') as f:
                pickle.dump(FS_PATH_REPLACEMENTS, f)
            with open(step4_dpath / 'seen_tasks.pkl', 'wb') as f:
                pickle.dump(seen_tasks, f)

        # Finally, update the file dates in the db.
        logger.info("[white]STEP 4. Update the file dates.")
        update_file_dates(LIBRARY_DB_STAGING_PATH, FS_PATH_REPLACEMENTS, seen_tasks)

        logger.info("")
        logger.info("[green]Jellyfin Database Migration complete.")
    logger.info(f"Log file written to: {config.log_file}")


def debug_staging_library(name, show_table=True):
    if 0:
        return
    # from rich.markup import escape
    import pandas as pd
    library_fpath = '/staging/staged-data/data/library.db'
    def niceview(d):
        if hasattr(d, 'hex'):
            return d.hex()
        else:
            return d

    orig_fpath = '/root/.local/share/jellyfin/data/library.db'
    orig_fpath_shm = '/root/.local/share/jellyfin/data/library.db-shm'
    orig_fpath_wal = '/root/.local/share/jellyfin/data/library.db-wal'

    print('-------')
    rich.print(f'[red][DEBUG] {name}: {library_fpath}  - {ub.hash_file(library_fpath)}')
    rich.print(f'[red][DEBUG] {name}: {orig_fpath}     - {ub.hash_file(orig_fpath)}')
    rich.print(f'[red][DEBUG] {name}: {orig_fpath_shm} - {ub.hash_file(orig_fpath_shm)}')
    rich.print(f'[red][DEBUG] {name}: {orig_fpath_wal} - {ub.hash_file(orig_fpath_wal)}')
    if show_table:
        uri = 'file:' + os.fspath(library_fpath) + '?mode=ro&immutable=1'
        con = sqlite3.connect(uri, uri=True)
        with con:
            # table_names = list(pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", con)['name'])
            table_name = 'TypedBaseItems'
            table = pd.read_sql_query(f"SELECT * FROM {table_name}", con)
            # Make bytes show as hex for readability
            table = table.map(niceview)
            print(table[['guid', 'Path']])
        rich.print(f'[red][DEBUG]{name}: {library_fpath} - {ub.hash_file(library_fpath)}')
    print('-------')

if __name__ == "__main__":
    main()
