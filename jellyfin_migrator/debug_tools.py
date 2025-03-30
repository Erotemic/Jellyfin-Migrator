#!/usr/bin/env python3
import sqlite3
import kwutil
import ubelt as ub
import pandas as pd
import rich
import scriptconfig as scfg


class DebugToolsCLI(scfg.DataConfig):
    root_dpath = scfg.Value(None, help='e.g. /config or /root/.local/share/jellyfin', position=1)
    include = scfg.Value('*', help='pattern for data to include')

    @classmethod
    def main(cls, argv=1, **kwargs):
        """
        Example:
            >>> # xdoctest: +SKIP
            >>> from jellyfin_migrator.debug_tools import *  # NOQA
            >>> argv = 0
            >>> kwargs = dict()
            >>> cls = DebugToolsCLI
            >>> config = cls(**kwargs)
            >>> cls.main(argv=argv, **config)
        """
        import rich
        from rich.markup import escape
        config = cls.cli(argv=argv, data=kwargs, strict=True)
        rich.print('config = ' + escape(ub.urepr(config, nl=1)))
        check_main_databases(config.root_dpath, config.include)


def check_main_databases(root_dpath, include='*'):
    """
    Perform a check on staged data to verify that paths are updated correctly.

    Ignore:
        root_dpath = ub.Path('~/.cache/jellyfin-migrator/staging/staged-data').expand()

    Ignore:
        /staging/staged-data/data/library.db
        sqlite3 /staging/staged-data/data/library.db "SELECT Path FROM TypedBaseItems

    """
    include_pat = kwutil.MultiPattern.coerce(include)
    root_dpath = ub.Path(root_dpath)
    jellyfin_db_fpath = (root_dpath / 'data/jellyfin.db')
    library_db_fpath = (root_dpath / 'data/library.db')

    database_fpath = jellyfin_db_fpath
    jellyfin_tables = report_sqlite_database(database_fpath, include_pat)  # NOQA

    database_fpath = library_db_fpath
    library_tables = report_sqlite_database(database_fpath, include_pat)  # NOQA

    # user_table = tables['Users']
    # rich.print(user_table.T.to_string())

    if include_pat.match('system.xml'):
        text = (root_dpath / 'config/system.xml').read_text()
        system_xml_data = kwutil.XML.loads(text)
        print(f'system_xml_data = {ub.urepr(system_xml_data, nl=3)}')

    if include_pat.match('mblink'):
        mblink_files = list((root_dpath / 'root').glob('**/*.mblink'))
        mblink_xml_files = list((root_dpath / 'root').glob('**/*.xml'))

        from rich.syntax import Syntax
        from rich.panel import Panel
        for fpath in mblink_files:
            rich.print(Panel(fpath.read_text(), title=str(fpath)))

        for fpath in mblink_xml_files:
            rich.print(Panel(Syntax(fpath.read_text(), 'xml'), title=str(fpath)))


def report_sqlite_database(database_fpath, include_pat):
    from rich.markup import escape
    import os

    assert database_fpath.exists()
    uri = 'file:' + os.fspath(database_fpath) + '?mode=ro&immutable=1'
    con = sqlite3.connect(uri, uri=True)

    # List all tables in the database
    table_names = list(pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", con)['name'])
    rich.print(f'[white]=== REPORT FOR: {database_fpath} - {len(table_names)}')

    def niceview(d):
        if hasattr(d, 'hex'):
            return d.hex()
        else:
            return d

    tables = {}
    for idx, table_name in enumerate(table_names, start=1):
        table = pd.read_sql_query(f"SELECT * FROM {table_name}", con)

        # Make bytes show as hex for readability
        table = table.map(niceview)

        tables[table_name] = table

    for idx, (table_name, table) in enumerate(tables.items()):
        if include_pat.match(table_name):
            column_names = table.columns.values.tolist()
            rich.print(f' - tablename: {table_name}')
            rich.print(f'   nRows: {len(table)}')
            rich.print(f'   nCols: {len(table.columns)}')

    for idx, (table_name, table) in enumerate(tables.items()):
        if include_pat.match(table_name):
            column_names = table.columns.values.tolist()
            rich.print(f' - tablename: {table_name}')
            rich.print(f'   nRows: {len(table)}')
            rich.print(f'   nCols: {len(table.columns)}')
            rich.print(ub.indent(f'columns = {ub.urepr(column_names, nl=1)}', '   '))
        ...

    for idx, (table_name, table) in enumerate(tables.items()):
        if include_pat.match(table_name):
            do_transpose = len(str(table.columns)) > 200
            rich.print(f'[white]--- {database_fpath} {idx} / {len(table_names)}')
            rich.print(f'[white]--- TABLE: {table_name} ---')
            if do_transpose:
                rich.print('[white]--- TRANSPOSED')
                if len(table) > 3:
                    rich.print('[white]--- TRUNCATED')
                    text = table.T.to_string(max_cols=5)
                else:
                    text = table.T.to_string()
            else:
                text = table.to_string()

            rich.print(f'[white]--- nRows={table.shape[0]}')
            rich.print(f'[white]--- nCols={table.shape[1]}')
            rich.print(f'[white]--- {ub.urepr(table.columns, nl=0)}')
            rich.print(escape(text))

            if table_name == 'TypedBaseItems':
                print('Hack to show all paths:')
                table = table.sort_values('Path')
                # rich.print(escape(table['Path'].to_string()))
                print('Hack to show all Ids:')
                selected = table[['guid', 'ParentId', 'TopParentId', 'Path', 'Images']].copy()
                # selected = selected.map(niceview)
                rich.print(escape(selected.to_string()))
                print('Hack to show data:')
                rich.print(escape(table['data'].to_string()))

    return tables

__cli__ = DebugToolsCLI

if __name__ == '__main__':
    """

    CommandLine:
        python ~/code/Jellyfin-Migrator/jellyfin_migrator/debug_tools.py
        python -m jellyfin_migrator.debug_tools
    """
    __cli__.main()
